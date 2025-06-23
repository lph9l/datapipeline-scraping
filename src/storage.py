# src/storage.py

import os
import json
import logging
import psycopg2
from airflow.models import Variable
from psycopg2.extras import execute_values, Json
from typing import Any, Dict, List

from .scrapers.config_loader import load_country_config

logger = logging.getLogger(__name__)
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://airflow:airflow@postgres/airflow'
)

# ── Leer país desde AIRFLOW env var ────────────────────────────────────────────
COUNTRY = Variable.get('COUNTRY', default_var='colombia').lower()
CONFIG_YML  = f"configs/{COUNTRY}.yml"

# Carga la sección "storage" del YAML de país
_cfg    = load_country_config(CONFIG_YML)['storage']
_raw    = _cfg['raw']
_final  = _cfg['final']
RAW_LOOKUP_KEY = _raw.get('lookup_key', 'no_camara')  # ahora genérico

def _connect():
    return psycopg2.connect(DATABASE_URL)

def _ddl_for(table: Dict[str, Any]) -> str:
    cols = [f"{name} {typ}" for name, typ in table['columns'].items()]
    pk   = table['primary_key']
    return (
        f"CREATE TABLE IF NOT EXISTS {table['table']} (\n  "
        + ",\n  ".join(cols)
        + f",\n  PRIMARY KEY({pk})\n);"
    )

def _upsert_sql_for(table: Dict[str, Any]) -> str:
    tbl = table['table']
    cols = list(table['columns'].keys())
    if tbl == _raw['table']:
        # omitimos last_seen en raw
        cols = [c for c in cols if c != 'last_seen']
    pk = table['primary_key']
    insert_cols = ", ".join(cols)
    updates     = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != pk)
    return (
        f"INSERT INTO {tbl} ({insert_cols}) VALUES %s "
        f"ON CONFLICT ({pk}) DO UPDATE SET {updates};"
    )

def ensure_raw_table():
    """Crea la tabla raw si no existe."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_ddl_for(_raw))

def ensure_final_table():
    """Crea la tabla final si no existe."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_ddl_for(_final))

def fetch_existing_raw() -> Dict[str, str]:
    """Devuelve dict(lookup_key → row_hash) de raw."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {RAW_LOOKUP_KEY}, {_raw['primary_key']} FROM {_raw['table']};"
            )
            return dict(cur.fetchall())

def fetch_final_by_ids(ids: List[str]) -> List[Dict[str, Any]]:
    """
    Dado un listado de valores de lookup_key, devuelve los registros completos de final.
    """
    table      = _final['table']
    cols       = list(_final['columns'].keys())
    lookup_key = _final.get('lookup_key', RAW_LOOKUP_KEY)
    sql        = f"SELECT {','.join(cols)} FROM {table} WHERE {lookup_key} = ANY(%s);"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (ids,))
            rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]

def upsert_raw(records: List[Dict[str, Any]]):
    """Inserta/actualiza en tabla raw."""
    expected_key = RAW_LOOKUP_KEY

    # 1) Renombrar 'no_camara' (o clave antigua) → expected_key, si aplica
    for r in records:
        if expected_key not in r and 'no_camara' in r:
            r[expected_key] = r.pop('no_camara')

    # 2) Filtrar registros sin valor en expected_key
    filtered = []
    for r in records:
        val = r.get(expected_key)
        if not val or (isinstance(val, str) and not val.strip()):
            logger.warning(f"Omitido registro sin '{expected_key}': {r}")
            continue
        filtered.append(r)

    # 3) Deduplicar por primary_key
    seen = set()
    deduped = []
    for rec in filtered:
        pkv = rec.get(_raw['primary_key'])
        if pkv and pkv not in seen:
            seen.add(pkv)
            deduped.append(rec)
        else:
            logger.warning(f"Ignorado registro duplicado raw: {rec}")

    # 4) Preparar SQL y valores
    sql  = _upsert_sql_for(_raw)
    cols = [c for c in _raw['columns'].keys() if c != 'last_seen']
    values = []
    for rec in deduped:
        values.append(tuple(rec.get(c) for c in cols))

    # 5) Ejecutar inserción/upsert
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_ddl_for(_raw))
            execute_values(cur, sql, values)
            logger.info(f"Upserted {len(values)} filas en {_raw['table']}")


def store_final(records: List[Dict[str, Any]]):
    """
    Inserta/actualiza en tabla final. Convierte 'documentos' a JSONB
    y normaliza fechas vacías a NULL.
    """
    sql   = _upsert_sql_for(_final)
    cols  = list(_final['columns'].keys())
    values = []
    for rec in records:
        row = []
        for c in cols:
            val = rec.get(c)
            if c == 'documentos':
                row.append(Json(val or []))
            else:
                if isinstance(val, str) and val.strip() == '':
                    row.append(None)
                else:
                    row.append(val)
        values.append(tuple(row))

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_ddl_for(_final))
            execute_values(cur, sql, values)
            logger.info(f"Stored/updated {len(values)} filas en {_final['table']}")

# Alias para los DAGs
ensure_raw_table         = ensure_raw_table
fetch_existing_checksums = fetch_existing_raw
upsert_raw               = upsert_raw
fetch_final_records      = fetch_final_by_ids
store_projects           = store_final
