import aiohttp
import random
from bs4 import BeautifulSoup

class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.failed_proxies = set()
        self.base_url = "https://free-proxy-list.net/"

    async def fetch_proxies(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, timeout=10) as resp:
                    html = await resp.text()
        except Exception as e:
            print(f"❌ Error al descargar proxies: {e}")
            return

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        table = soup.find("table", id="proxylisttable") or soup.find("table")
        if not table:
            print("❌ No se encontró ninguna tabla en la página")
            return

        rows = table.find_all("tr")
        self.proxies.clear()
        self.failed_proxies.clear()

        count = 0
        for tr in rows[1:]:
            cols = tr.find_all("td")
            if len(cols) < 7:
                continue
            ip = cols[0].text.strip()
            port = cols[1].text.strip()
            https = cols[6].text.strip().lower()
            if https == "yes":
                self.proxies.append(f"http://{ip}:{port}")
                count += 1
                if count >= 50:
                    break

        print(f"🌐 Proxies obtenidos: {len(self.proxies)}")
        for p in self.proxies[:5]:
            print(f"🔹 {p}")

    async def is_proxy_working(self, proxy: str) -> bool:
        test_url = "https://httpbin.org/ip"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(test_url, proxy=proxy, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        print(f"✅ Proxy válido: {proxy} → IP: {data['origin']}")
                        return True
        except Exception as e:
            print(f"❌ Proxy falló: {proxy} → {e}")
        return False

    async def get_random_valid_proxy(self):
        if not self.proxies:
            await self.fetch_proxies()

        available_proxies = [p for p in self.proxies if p not in self.failed_proxies]

        if not available_proxies:
            print("♻️ Todos los proxies fallaron. Refrescando lista.")
            self.failed_proxies.clear()
            await self.fetch_proxies()
            available_proxies = self.proxies.copy()

        random.shuffle(available_proxies)

        for proxy in available_proxies:
            if await self.is_proxy_working(proxy):
                return proxy
            else:
                self.failed_proxies.add(proxy)

        print("❌ No hay proxies válidos disponibles en este ciclo.")
        return None

    async def get_proxy(self):
        return await self.get_random_valid_proxy()
