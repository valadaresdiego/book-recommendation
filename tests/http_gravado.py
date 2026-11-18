"""Transporte falso do `httpx` que serve as respostas gravadas em `tests/dados/http/` (SPEC §12)."""

from pathlib import Path

import httpx

PASTA = Path(__file__).parent / "dados" / "http"


class TransporteGravado(httpx.MockTransport):
    """Responde com o arquivo gravado do caminho pedido, ou 404. Guarda os caminhos pedidos."""

    def __init__(self, pasta: Path = PASTA, erro: Exception | None = None) -> None:
        self.pedidos: list[str] = []
        self._pasta = pasta
        self._erro = erro
        super().__init__(self._responder)

    def _responder(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido.url.path)
        if self._erro is not None:
            raise self._erro
        arquivo = self._arquivo(pedido.url)
        if pedido.url.host == "www.googleapis.com" and arquivo and not arquivo.exists():
            # Uma busca sem resultado no Google Books é um 200 sem `items`.
            return httpx.Response(200, json={"kind": "books#volumes", "totalItems": 0})
        if arquivo is None or not arquivo.exists():
            return httpx.Response(404, json={"error": "notfound"})
        return httpx.Response(
            200, content=arquivo.read_bytes(), headers={"content-type": "application/json"}
        )

    def _arquivo(self, url: httpx.URL) -> Path | None:
        if url.host == "openlibrary.org":
            return self._pasta / "ol" / url.path.lstrip("/")
        if url.host == "www.googleapis.com":
            q = url.params.get("q", "").replace(":", "_").replace(" ", "_")
            return self._pasta / "gb" / f"{q}.json"
        return None
