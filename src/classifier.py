# src/classifier.py

import os
import re
import json
import logging
from typing import List, Dict, Any
from airflow.models import Variable
import yaml
from google import genai

from .scrapers.config_loader import load_country_config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Cargar classifier.yml ──────────────────────────────────────────────────────
CFG_PATH = os.getenv('CLASSIFIER_CONFIG', '/opt/airflow/configs/classifier.yml')
with open(CFG_PATH, 'r', encoding='utf-8') as f:
    clf_cfg = yaml.safe_load(f)


# ── Leer país desde AIRFLOW env var ────────────────────────────────────────────
COUNTRY = Variable.get('COUNTRY', default_var='colombia').lower()
CONFIG_YML  = f"configs/{COUNTRY}.yml"

# Parámetros de Gemini
api_cfg    = clf_cfg.get('gemini', {})
MODEL_NAME = os.getenv('GEMINI_MODEL', api_cfg.get('model', 'gemini-2.5-flash'))
BATCH_SIZE = int(os.getenv('GEMINI_BATCH_SIZE', api_cfg.get('batch_size', 20)))
API_KEY    = os.getenv('GEMINI_API_KEY')
if not API_KEY:
    logger.warning("GEMINI_API_KEY no está definido; las llamadas a Gemini fallarán")

# Cliente genai
client = genai.Client(api_key=API_KEY)

# ── Cargar lookup_key desde archivo de país ────────────────────────────────────
country_cfg    = load_country_config(os.getenv('COUNTRY_CONFIG', CONFIG_YML))
raw_cfg        = country_cfg['storage']['raw']
RAW_LOOKUP_KEY = raw_cfg.get('lookup_key', 'no_camara')

raw_classifier        = country_cfg.get('classifier', {})
CLASSIFIER_TITTLE     = raw_classifier.get('titulo', 'titulo')
CLASSIFIER_DETAIL     = raw_classifier.get('detalle', 'objeto')

# ── Categorías y reglas ───────────────────────────────────────────────────────
if 'categories' not in clf_cfg or not isinstance(clf_cfg['categories'], list):
    raise RuntimeError(f"'categories' faltan o invalidas en {CFG_PATH}")
CATEGORIES = clf_cfg['categories']

raw_rules = clf_cfg.get('rules', [])
RULES: List[tuple] = []
for idx, spec in enumerate(raw_rules):
    pat = spec.get('pattern')
    cat = spec.get('category')
    if not pat or not cat:
        logger.warning(f"[classifier] Ignorando regla #{idx} malformada: {spec!r}")
        continue
    try:
        RULES.append((re.compile(pat, re.IGNORECASE), cat))
    except re.error as e:
        logger.warning(f"[classifier] Regex inválido en regla #{idx}: {e}")

logger.info(f"[classifier] Cargadas {len(RULES)} reglas de configuración")


def _apply_rules(text: str) -> str:
    for regex, label in RULES:
        if regex.search(text):
            return label
    return ''


def _call_gemini(batch: List[Dict[str, Any]]) -> Dict[str, str]:
    # Construir prompt con el lookup key dinámico
    lines = [
        f"{item.get(RAW_LOOKUP_KEY, '')}: {item.get(CLASSIFIER_TITTLE, '')} -- {item.get(CLASSIFIER_DETAIL, '')}"
        for item in batch
    ]

    prompt = (
        "Agrupa **exclusivamente** cada uno de estos proyectos en uno de los siguientes sectores económicos:\n"
        f"{', '.join(CATEGORIES)}.\n"
        "Si no encaja claramente en ninguno, entonces clasifícalo como \"otros\".\n"
        "Respóndeme un JSON-Array con objetos de la forma:\n"
        "  {\"id\": \"<ID_DEL_PROYECTO>\", \"label\": \"<categoría>\"}\n"
        "sin ningún texto adicional.\n\n"
        + "\n".join(lines)
    )
    logger.info(f"[classifier] Enviando batch de {len(batch)} a Gemini")
    try:
        resp = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        parts = resp.candidates[0].content.parts
        raw = "".join(getattr(p, 'text', '') for p in parts).strip()
        logger.info(f"[classifier] Respuesta bruta Gemini:\n{raw}")
        results = json.loads(raw)
    except Exception as e:
        logger.error(f"[classifier] Error llamando a Gemini o parseando JSON: {e}")
        return {}

    if not isinstance(results, list):
        logger.error(f"[classifier] Formato inesperado: {type(results)} (esperaba lista)")
        return {}

    if len(results) != len(batch):
        logger.error(
            f"[classifier] Gemini devolvió {len(results)} items, esperaba {len(batch)}"
        )

    mapping: Dict[str, str] = {}
    for rec in results:
        key = rec.get('id')
        val = rec.get('label')
        if key and val:
            mapping[key] = val
        else:
            logger.warning(f"[classifier] Ignorando registro inválido: {rec!r}")

    return mapping


def classify_by_sector(proyectos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # 1) Aplicar reglas locales
    unresolved: List[Dict[str, Any]] = []
    for p in proyectos:
        text = f"{p.get(CLASSIFIER_TITTLE, '')} {p.get(CLASSIFIER_DETAIL, '')}"
        label = _apply_rules(text)
        if label:
            p['sector'] = label
        else:
            p['sector'] = ''
            unresolved.append(p)
    logger.info(
        f"[classifier] {len(proyectos) - len(unresolved)} clasificados por regla, "
        f"{len(unresolved)} pendientes"
    )

    # 2) Llamar a Gemini en batches
    for i in range(0, len(unresolved), BATCH_SIZE):
        batch = unresolved[i : i + BATCH_SIZE]
        mapping = _call_gemini(batch)
        logger.info(f"[classifier] Mapeo recibido para batch {i}-{i+len(batch)-1}: {mapping}")
        for p in batch:
            p['sector'] = mapping.get(p.get(RAW_LOOKUP_KEY, ''), 'otros')

    # 3) Validación final
    for p in proyectos:
        if p['sector'] not in CATEGORIES:
            logger.warning(
                f"[classifier] Sector '{p['sector']}' no válido para {p.get(RAW_LOOKUP_KEY)}, "
                "asignando 'otros'"
            )
            p['sector'] = 'otros'

    return proyectos
