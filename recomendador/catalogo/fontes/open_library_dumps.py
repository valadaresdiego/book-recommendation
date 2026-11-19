"""Download dos dumps mensais da Open Library (SPEC §5): `works`, `editions` e `authors`, ~13 GB.

O `authors` dá os nomes dos autores das Obras técnicas (`carregar-tecnicas`, §8.8).
"""

import logging
from pathlib import Path

import httpx

URLS = {
    "editions": "https://openlibrary.org/data/ol_dump_editions_latest.txt.gz",
    "works": "https://openlibrary.org/data/ol_dump_works_latest.txt.gz",
    "authors": "https://openlibrary.org/data/ol_dump_authors_latest.txt.gz",
}

log = logging.getLogger(__name__)


def baixar(destino: Path, user_agent: str) -> None:
    """Baixa os dumps que faltam em `destino`. Retoma de onde parou se o download cair."""
    destino.mkdir(parents=True, exist_ok=True)
    for tipo, url in URLS.items():
        final = destino / f"ol_dump_{tipo}_latest.txt.gz"
        if final.exists():
            continue
        parcial = final.with_suffix(".gz.parcial")
        inicio = parcial.stat().st_size if parcial.exists() else 0
        headers = {"User-Agent": user_agent}
        if inicio:
            headers["Range"] = f"bytes={inicio}-"
        log.info("Baixando %s (a partir do byte %d)", url, inicio)
        with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            modo = "ab" if inicio and r.status_code == 206 else "wb"
            with parcial.open(modo) as f:
                for pedaco in r.iter_bytes(1 << 20):
                    f.write(pedaco)
        parcial.replace(final)
