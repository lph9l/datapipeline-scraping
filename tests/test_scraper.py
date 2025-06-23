# tests/test_scraper.py
import hashlib
import json
import pytest
import src.scrapers.scraper as scraper_module
from src.scrapers.scraper import DynamicScraper


def test_compute_checksum(monkeypatch):
    """
    Aísla el cálculo de checksum de un elemento basado
    en campos configurados. Se parchea load_country_config para
    inyectar una configuración mínima con ['id','name'] como campos.
    El hash MD5 debe coincidir con la serialización JSON ordenada.
    """
    # Configuración mínima para el hash
    fake_cfg = {
        'selectors': {'list': {'hash': {'fields': ['id', 'name'], 'key': 'checksum'}}},
        'portal': {'domain': 'example.com', 'base_url': 'http://example.com'},
        'retry': {},
        'concurrency': {},
        'pipeline': []
    }
    # Monkeypatch: sustituye carga real de YAML por fake_cfg
    monkeypatch.setattr(scraper_module, 'load_country_config', lambda path: fake_cfg)

    # Inicializamos el scraper con ruta dummy (ignorará el fichero)
    ds = DynamicScraper('dummy_path')
    item = {'id': '123', 'name': 'Test Name', 'extra': 'ignored'}

    # Cálculo esperado: MD5 sobre JSON sorted_keys de sólo 'id' y 'name'
    base = {'id': '123', 'name': 'Test Name'}
    s = json.dumps(base, sort_keys=True, ensure_ascii=False)
    expected = hashlib.md5(s.encode('utf-8')).hexdigest()

    assert ds._compute_checksum(item) == expected
