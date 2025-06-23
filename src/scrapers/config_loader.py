# src/scrapers/config_loader.py

import os
from pathlib import Path
import yaml

# Calculamos la raíz del proyecto (dos niveles arriba de este fichero)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

def load_country_config(path: str) -> dict:
    """
    Carga un fichero YAML de configuración.
    Si 'path' no existe directamente, intenta cargarlo desde PROJECT_ROOT/path.
    """
    p = Path(path)
    if not p.is_file():
        p = PROJECT_ROOT / path
    if not p.is_file():
        raise FileNotFoundError(f"Config file no encontrado: {path!r}")
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)
