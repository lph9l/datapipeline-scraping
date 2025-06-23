import os
import asyncio
import logging
import hashlib
import json
from collections import deque
from tenacity import retry, stop_after_attempt, wait_exponential, wait_fixed, wait_random
from .config_loader import load_country_config
from .network.http_client    import create_session, fetch
from .list_parser    import GenericListParser
from .detail_parser  import GenericDetailParser
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

PARSERS = {
    'GenericListParser'  : GenericListParser,
    'GenericDetailParser': GenericDetailParser,
}

class DynamicScraper:
    def __init__(self, cfg_path: str):
        self.cfg = load_country_config(cfg_path)
        self.domain = self.cfg['portal']['domain']
        # Construye self.fetch con retry dinámico
        self._build_fetch_with_retry(self.cfg.get('retry', {}))

        # Configuración de hash
        hash_cfg = self.cfg['selectors']['list'].get('hash', {})
        self.hash_key    = hash_cfg.get('key', 'checksum')
        self.hash_fields = hash_cfg.get('fields', [])

    def _build_fetch_with_retry(self, retry_cfg):
        attempts = retry_cfg.get('attempts', 3)
        backoff  = retry_cfg.get('backoff', {})
        if backoff.get('type') == 'fixed':
            wait_strategy = wait_fixed(backoff.get('multiplier', 1))
        else:
            wait_strategy = wait_exponential(
                multiplier=backoff.get('multiplier', 1),
                max=backoff.get('max_delay', 30)
            )
        if backoff.get('jitter', False):
            wait_strategy = wait_strategy + wait_random(0,1)

        # Decoramos fetch con tenacity
        self.fetch = retry(
            stop=stop_after_attempt(attempts),
            wait=wait_strategy,
            reraise=True
        )(fetch)

    def _compute_checksum(self, item: dict) -> str:
        base = {k: item.get(k, '') for k in self.hash_fields}
        s = json.dumps(base, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    async def _run_stage(self, session, items, stage_cfg):
        parser_cls = PARSERS[stage_cfg['parser']]
        parser     = parser_cls(self.cfg)

        conc    = self.cfg['concurrency'].get(stage_cfg['concurrency'], 1)
        pending = deque()
        results = []

        # Montar pending inicial según tipo
        if stage_cfg['type'] == 'list':
            maxp = stage_cfg.get('max_pages', 1)
            base = self.cfg['portal']['base_url']
            urls = [base] + [f"{base}?page={i}" for i in range(1, maxp)]
            for u in urls:
                pending.append({'url': u})
        else:
            key = stage_cfg.get('input_key', 'detail_url')
            for it in items:
                url = it.get(key)
                if url:
                    pending.append({'url': url, 'meta': it})
                else:
                    # Sin URL, pasamos directo
                    results.append(it)

        round_idx = 0
        while pending:
            round_idx += 1
            batch = [pending.popleft() for _ in range(min(conc, len(pending)))]
            logger.info(f"[{stage_cfg['name']}] Round {round_idx}: {len(batch)} URLs @conc={conc}")

            # Ejecutar todos los fetch con tenacity interna
            tasks = [self.fetch(session, b['url']) for b in batch]
            pages = await asyncio.gather(*tasks, return_exceptions=True)

            failed = []
            for b, content in zip(batch, pages):
                if isinstance(content, str):
                    # Éxito de fetch
                    if stage_cfg['type'] == 'list':
                        parsed = parser.parse(content)
                        for item in parsed:
                            if self.hash_fields:
                                item[self.hash_key] = self._compute_checksum(item)
                        results.extend(parsed)
                    else:
                        # En detalle, parseamos y actualizamos meta
                        detail = parser.parse(content)
                        b['meta'].update(detail)
                        results.append(b['meta'])
                else:
                    # Content es Exception: 
                    if stage_cfg['type'] == 'detail':
                        # Abortamos TODO el stage para que Airflow reintente la task
                        logger.error(f"Error crítico en detalle [{b['url']}]: {content!r}")
                        raise content
                    # Para list, reintentamos más adelante
                    failed.append(b)

            # Ajuste dinámico de concurrencia (solo para list)
            err = len(failed) / len(batch)
            max_conc = self.cfg['concurrency'].get(stage_cfg['concurrency'], conc)
            if err < 0.05 and conc < max_conc:
                conc = min(self.cfg['concurrency'].get(stage_cfg['concurrency'], 1), 10)


            # Requeue de los fallidos (solo en list)
            for b in (failed if err <= 0.10 else reversed(failed)):
                pending.append(b)

        return results

    async def run_async(self):
        session = create_session()
        try:
            items = []
            for stage in self.cfg['pipeline']:
                items = await self._run_stage(session, items, stage)
            return items
        finally:
            await session.close()

    def run(self):
        return asyncio.run(self.run_async())

    # Métodos para DAG incremental
    async def _run_list(self):
        session = create_session()
        try:
            return await self._run_stage(session, [], self.cfg['pipeline'][0])
        finally:
            await session.close()

    def run_list(self):
        return asyncio.run(self._run_list())

    async def _run_detail(self, items):
        session = create_session()
        try:
            stage = next(s for s in self.cfg['pipeline'] if s['type']=='detail')
            return await self._run_stage(session, items, stage)
        finally:
            await session.close()

    def run_detail(self, items):
        return asyncio.run(self._run_detail(items))
