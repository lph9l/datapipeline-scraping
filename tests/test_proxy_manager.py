# tests/test_proxy_manager.py
import os
import sys
import pytest
import asyncio

# Incluye la raíz del proyecto para resolver src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import src.scrapers.network.proxy_manager as pm_module
from src.scrapers.network.proxy_manager import ProxyManager


def test_get_proxy_rotation(monkeypatch):
    """
    Valida que get_proxy (async) retorne uno de los proxies disponibles,
    stubendo get_random_valid_proxy para devolver siempre el primero.
    """
    proxies = ['http://p1', 'http://p2']
    async def fake_random(self):
        return proxies[0]
    monkeypatch.setattr(pm_module.ProxyManager, 'get_random_valid_proxy', fake_random)

    pm = ProxyManager()
    result = asyncio.run(pm.get_proxy())
    assert result in proxies