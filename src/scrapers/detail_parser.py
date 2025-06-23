# src/scrapers/detail_parser.py

import re
import logging
import requests
from lxml import html as lxml_html
from urllib.parse import urljoin, urlparse, urlunparse
from typing import Any, Dict

logger = logging.getLogger(__name__)

class GenericDetailParser:
    def __init__(self, cfg: dict):
        d = cfg['selectors']['detail']
        self.domain = cfg['portal']['domain']
        self.fields = d['fields']

    def parse(self, html_body: str) -> Dict[str, Any]:
        tree = lxml_html.fromstring(html_body)
        full_txt = tree.text_content()
        result: Dict[str, Any] = {}

        # 1) Extraer según spec
        for field_name, spec in self.fields.items():
            if 'xpath' in spec:
                nodes = tree.xpath(spec['xpath'])
                if spec.get('multiple', False):
                    out, seen = [], set()
                    for node in nodes:
                        # texto o attr
                        if isinstance(node, str):
                            raw = node.strip()
                        elif 'attr' in spec:
                            raw = node.get(spec['attr'], '').strip()
                        else:
                            raw = node.text_content().strip()
                        # regex
                        if 'regex' in spec and raw:
                            m = re.search(spec['regex'], raw, re.IGNORECASE | re.DOTALL)
                            raw = m.group(1).strip() if m else ''
                        if not raw:
                            continue
                        url = None
                        if 'attr' in spec and not isinstance(node, str):
                            href = node.get(spec['attr'], '').strip()
                            url = urljoin(self.domain, href)
                            if url in seen:
                                continue
                            seen.add(url)
                        # etiqueta
                        if isinstance(node, str):
                            lbl = raw
                        else:
                            label_attr = spec.get('label_attr')
                            if label_attr == 'text':
                                lbl = node.text_content().strip()
                            elif label_attr and node.get(label_attr):
                                lbl = node.get(label_attr).strip()
                            else:
                                lbl = raw
                        out.append({'label': lbl, 'url': url} if url else raw)
                    result[field_name] = out
                else:
                    if not nodes:
                        text_val = ''
                    else:
                        node = nodes[0]
                        if isinstance(node, str):
                            text_val = node.strip()
                        elif 'attr' in spec:
                            text_val = node.get(spec['attr'], '').strip()
                        else:
                            text_val = node.text_content().strip()
                        if 'regex' in spec and text_val:
                            m = re.search(spec['regex'], text_val, re.IGNORECASE | re.DOTALL)
                            text_val = m.group(1).strip() if m else ''
                    result[field_name] = text_val

            elif spec.get('find_all') and 'regex' in spec:
                matches = re.findall(spec['regex'], full_txt, re.IGNORECASE | re.DOTALL)
                idx = spec.get('index', 0)
                result[field_name] = matches[idx].strip() if len(matches) > idx else ''

            elif spec.get('block_after') and 'regex' in spec:
                block = full_txt.split(spec['block_after'], 1)[1] if spec['block_after'] in full_txt else full_txt
                m = re.search(spec['regex'], block, re.IGNORECASE | re.DOTALL)
                result[field_name] = m.group(1).strip() if m else ''

            elif 'regex' in spec:
                m = re.search(spec['regex'], full_txt, re.IGNORECASE | re.DOTALL)
                result[field_name] = m.group(1).strip() if m else ''

            else:
                logger.warning(f"No hay método para extraer «{field_name}»")
                result[field_name] = None

        # 2) Si no hay documentos, seguimos el enlace de expediente
        docs = result.get('documentos', [])
        expediente_path = result.get('expediente_url')
        if not docs and expediente_path:
            # Construir URL completa y forzar HTTPS
            expediente_url = urljoin(self.domain, expediente_path)
            parsed = urlparse(expediente_url)
            if parsed.scheme != 'https':
                parsed = parsed._replace(scheme='https', netloc=parsed.netloc)
                expediente_url = urlunparse(parsed)

            try:
                resp = requests.get(expediente_url, timeout=15)
                resp.raise_for_status()
                sub_tree = lxml_html.fromstring(resp.content)
                pdf_links = []
                for a in sub_tree.xpath("//a[contains(translate(@href,'PDF','pdf'),'.pdf')]"):
                    href = a.get('href', '').strip()
                    if href:
                        pdf_links.append(urljoin(self.domain, href))
                result['documentos'] = pdf_links
            except Exception as e:
                logger.warning(f"Error al extraer PDFs de expediente ({expediente_url}): {e}")

        logger.info(f"Detalle parseado: {{ {', '.join(result.keys())} }}")
        return result
