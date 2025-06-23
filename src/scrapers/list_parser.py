import re
import logging
from urllib.parse import urljoin
from selectolax.parser import HTMLParser
from typing import Any, List, Dict

logger = logging.getLogger(__name__)

class GenericListParser:
    def __init__(self, cfg: dict):
        lst = cfg['selectors']['list']
        self.row_sel    = lst['row_selector']
        self.cell_sel   = lst['cell_selector']
        self.fields     = lst['fields']
        self.link_excl  = lst.get('detail_link_exclude', {})
        self.title_re   = re.compile(lst.get('title_regex', '.*'), re.DOTALL)
        self.domain     = cfg['portal']['domain']
        self.link_sel   = lst.get('detail_link_selector')

        # Determine key field (first in fields dict)
        self.key_field = next(iter(self.fields.keys()))

        # Map field names to column index
        self.field_pos = {}
        for name, sel in self.fields.items():
            m = re.match(r'td:nth-child\((\d+)\)', sel)
            if m:
                self.field_pos[name] = int(m.group(1)) - 1

        # Determine link column index
        m = re.match(r'td:nth-child\((\d+)\)', self.link_sel or '')
        self.link_idx = int(m.group(1)) - 1 if m else None

    def parse(self, html_content: str) -> List[Dict[str, Any]]:
        doc = HTMLParser(html_content)
        rows = [r for r in doc.css(self.row_sel) if r.css(self.cell_sel)]
        items = []

        for row in rows:
            cells = row.css(self.cell_sel)
            # skip rows without enough cells
            if not cells or len(cells) <= max(self.field_pos.values(), default=-1):
                continue

            # extract fields
            data: Dict[str, Any] = {}
            for name, idx in self.field_pos.items():
                data[name] = cells[idx].text().strip()

            # skip header row if key field empty or equals its own name
            key_val = data.get(self.key_field, '')
            if not key_val or key_val.lower() == self.key_field.lower():
                continue

            # detail_url
            detail_url = ''
            if self.link_idx is not None and self.link_idx < len(cells):
                for a in cells[self.link_idx].css('a'):
                    href = (a.attributes.get('href') or '').strip()
                    txt  = a.text().strip().lower()
                    if self.link_excl.get('href_suffix') and href.lower().endswith(self.link_excl['href_suffix']):
                        continue
                    if self.link_excl.get('text') and self.link_excl['text'] in txt:
                        continue
                    detail_url = urljoin(self.domain, href)
                    break
            data['detail_url'] = detail_url

            # titulo via regex or fallback
            inner = cells[self.link_idx].html if self.link_idx is not None and self.link_idx < len(cells) else ''
            m = self.title_re.search(inner or '')
            if m and m.groups():
                data['titulo'] = m.group(1).strip()
            else:
                # fallback: use whatever field named 'titulo' or the key_field
                data['titulo'] = data.get('titulo') or data.get(self.key_field, '')

            items.append(data)

        logger.info(f"Parsed {len(items)} valid rows (skipped headers and malformed)")
        return items
