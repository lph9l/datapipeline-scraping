import os
import logging
import random
import aiohttp
from aiohttp import ClientTimeout, ClientResponseError
from .proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 15))
TIMEOUT = ClientTimeout(total=REQUEST_TIMEOUT)

proxy_manager = ProxyManager()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:93.0) Gecko/20100101 Firefox/93.0",
]

def get_random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive"
    }

async def fetch(session: aiohttp.ClientSession, url: str) -> str:
    headers = get_random_headers()

    # 1. Intento sin proxy
    try:
        logger.debug(f"[FETCH] Intento sin proxy: {url}")
        async with session.get(url, timeout=TIMEOUT, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.text()
    except Exception as e:
        logger.warning(f"[FETCH] Falló sin proxy: {e!r}")

    # 2. Buscar y usar un proxy funcional
    for attempt in range(20):  # Máximo 5 intentos de encontrar proxy funcional
        proxy = await proxy_manager.get_random_valid_proxy()
        if not proxy:
            logger.error("[FETCH] No hay proxies válidos disponibles.")
            raise Exception("No hay proxies válidos disponibles.")

        try:
            logger.debug(f"[FETCH] Usando proxy {proxy} (intento {attempt+1})")
            async with session.get(url, timeout=TIMEOUT, headers=get_random_headers(), proxy=proxy) as resp:
                resp.raise_for_status()
                logger.info(f"[FETCH] ✅ Éxito con proxy {proxy}")
                return await resp.text()
        except ClientResponseError as ce:
            logger.warning(f"[FETCH] Proxy {proxy} bloqueado: {ce.status}")
            if ce.status in {403, 429}:
                continue  # Buscar otro
            raise
        except Exception as e:
            logger.warning(f"[FETCH] Proxy {proxy} falló: {e!r}")
            continue

    raise Exception(f"[FETCH] Fallaron todos los proxies para: {url}")

def create_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(timeout=TIMEOUT)
