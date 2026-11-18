"""Download do goodbooks-10k (Releases do GitHub, CC BY-SA 4.0; ADR 0003)."""

import logging
import zipfile
from pathlib import Path

import httpx

URL_ZIP = "https://github.com/zygmuntz/goodbooks-10k/releases/download/v1.0/goodbooks-10k.zip"
ARQUIVOS = ("books.csv", "ratings.csv", "tags.csv", "book_tags.csv")

log = logging.getLogger(__name__)


def garantir_arquivos(destino: Path) -> None:
    """Deixa os CSVs em `destino`, extraindo do zip e baixando o zip só se faltar."""
    if all((destino / a).exists() for a in ARQUIVOS):
        return
    destino.mkdir(parents=True, exist_ok=True)
    zip_local = destino / "goodbooks-10k.zip"
    if not zip_local.exists():
        log.info("Baixando %s", URL_ZIP)
        parcial = zip_local.with_suffix(".zip.parcial")
        with httpx.stream("GET", URL_ZIP, follow_redirects=True, timeout=60) as resp:
            resp.raise_for_status()
            with parcial.open("wb") as f:
                for pedaco in resp.iter_bytes():
                    f.write(pedaco)
        parcial.replace(zip_local)
    with zipfile.ZipFile(zip_local) as z:
        for a in ARQUIVOS:
            z.extract(a, destino)
