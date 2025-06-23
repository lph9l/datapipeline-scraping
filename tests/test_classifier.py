# tests/test_classifier.py
import os
import sys
import types
import importlib
import re
import pytest


def import_classifier(monkeypatch):
    """
    Prepara un entorno aislado para src.classifier:
    - Crea dinámicamente un classifier.yml con categorías, reglas y sección gemini.
    - Define GEMINI_API_KEY para evitar warnings.
    - Stub de google.genai.Client para no llamar a la API real.
    - Stub de airflow.models.Variable.get y config_loader.
    - Añade root al sys.path para import src.classifier.
    """
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    # YAML mínimo para pruebas de reglas y categorías
    yaml_content = '''categories:
  - sector_valid
  - otros
rules:
  - pattern: foo
    category: sector_foo
gemini:
  model: test_model
  batch_size: 2
'''
    config_path = os.path.join(root, 'classifier.yml')
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)

    # Variables de entorno: ruta y clave dummy
    monkeypatch.setenv('CLASSIFIER_CONFIG', config_path)
    monkeypatch.setenv('GEMINI_API_KEY', 'dummy_key')

    # Stub de cliente Google GenAI (no hace nada)
    genai_mod = types.ModuleType('google.genai')
    genai_mod.Client = lambda api_key=None: None
    google_mod = types.ModuleType('google')
    google_mod.genai = genai_mod
    sys.modules['google'] = google_mod
    sys.modules['google.genai'] = genai_mod

    # Añadir root al path para importar src
    sys.path.insert(0, root)

    # Stub de Variable.get para airflow
    airflow_mod = types.ModuleType('airflow')
    sys.modules['airflow'] = airflow_mod
    models_mod = types.ModuleType('airflow.models')
    class DummyVar:
        @staticmethod
        def get(key, default_var=None):
            return default_var
    models_mod.Variable = DummyVar
    sys.modules['airflow.models'] = models_mod

    # Stub de config_loader que usa classifier
    loader_mod = types.ModuleType('src.scrapers.config_loader')
    loader_mod.load_country_config = lambda path: {
        'storage': {'raw': {'lookup_key': 'id'}},
        'classifier': {'titulo': 'title', 'detalle': 'detail'}
    }
    sys.modules['src.scrapers.config_loader'] = loader_mod

    import src.classifier as classifier_mod
    importlib.reload(classifier_mod)
    return classifier_mod


def test_apply_rules(monkeypatch):
    """
    Verifica que _apply_rules aplica la primera expresión
    regular coincidente (case-insensitive) y devuelve la categoría.
    Retorna cadena vacía si no hay match.
    """
    clsf = import_classifier(monkeypatch)
    clsf.RULES = [(re.compile('foo', re.IGNORECASE), 'sector_foo')]

    assert clsf._apply_rules('This Foo test') == 'sector_foo'
    assert clsf._apply_rules('nothing here') == ''


def test_classify_by_sector_fallback(monkeypatch):
    """
    Comprueba el flujo de classify_by_sector:
    1) Sin reglas locales, invoca _call_gemini stubeado.
    2) Asigna categoría válida si está en CATEGORIES.
    3) Si Gemini devuelve algo no listado, cae a 'otros'.
    """
    clsf = import_classifier(monkeypatch)
    clsf.RULES = []
    clsf.CATEGORIES = ['sector_valid', 'otros']
    clsf.RAW_LOOKUP_KEY = 'id'
    clsf.CLASSIFIER_TITTLE = 'title'
    clsf.CLASSIFIER_DETAIL = 'detail'

    # Stub para la llamada a Gemini
    def fake_call(batch):
        return {'1': 'sector_valid', '2': 'invalid_sector'}
    monkeypatch.setattr(clsf, '_call_gemini', fake_call)

    proyectos = [
        {'id': '1', 'title': 'Proj1', 'detail': 'Detail1'},
        {'id': '2', 'title': 'Proj2', 'detail': 'Detail2'}
    ]
    result = clsf.classify_by_sector([p.copy() for p in proyectos])

    assert result[0]['sector'] == 'sector_valid'
    assert result[1]['sector'] == 'otros'