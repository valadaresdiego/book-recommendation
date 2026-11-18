"""Cliente da API da Open Library (SPEC §5): `/isbn/{isbn}.json` e `/works/{key}.json`.

Serve à regra 2 e à 3 da resolução Edição → Obra (SPEC §7.2) e ao enriquecimento das Obras
do Leitor no `atualizar` (SPEC §10). O limite é de 1 req/s, garantido aqui mesmo, e o
`User-Agent` identifica o app com um contato, como a Open Library pede.
"""

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from recomendador.catalogo.fontes import FonteIndisponivel
from recomendador.catalogo.isbn import normalizar_isbn

URL_BASE = "https://openlibrary.org"
URL_CAPA = "https://covers.openlibrary.org/b/id/{}-M.jpg"
ASSUNTOS_POR_OBRA = 30
_MAX_REDIRECIONAMENTOS = 3
_RE_ANO = re.compile(r"\b(\d{4})\b")


@dataclass(frozen=True)
class EdicaoOL:
    chave: str  # /books/OL...M
    titulo: str
    works: tuple[str, ...]  # /works/OL...W, na ordem da Open Library
    isbns: tuple[str, ...]  # ISBN-13
    idiomas: tuple[str, ...]  # códigos MARC: por, eng...
    traducao_de: str | None  # `translation_of`: o título original
    titulos_da_obra: tuple[str, ...]  # `work_titles`
    ano: int | None
    editora: str | None
    capa_url: str | None


@dataclass(frozen=True)
class ObraOL:
    chave: str  # a chave final, depois de seguir redirecionamentos
    titulo: str
    descricao: str | None
    assuntos: tuple[str, ...]
    ano: int | None
    capa_url: str | None


def texto_descricao(valor: object) -> str | None:
    """`description` vem como texto ou como `{"type": "/type/text", "value": ...}`."""
    if isinstance(valor, dict):
        valor = valor.get("value")
    if isinstance(valor, str) and valor.strip():
        return valor.strip()
    return None


def assuntos(valor: object) -> list[str]:
    """`subjects` em minúsculas, sem repetição, com no máximo 30 por Obra."""
    vistos: dict[str, None] = {}
    for s in valor if isinstance(valor, list) else []:
        if isinstance(s, str) and (limpo := " ".join(s.split()).lower()) and len(limpo) <= 100:
            vistos.setdefault(limpo)
    return list(vistos)[:ASSUNTOS_POR_OBRA]


def ano_de(data: object) -> int | None:
    anos = _RE_ANO.findall(str(data or ""))
    return int(anos[-1]) if anos else None


def _capa(dados: dict) -> str | None:
    ids = [c for c in dados.get("covers") or [] if isinstance(c, int) and c > 0]
    return URL_CAPA.format(ids[0]) if ids else None


def _chaves(itens: object, campo: str = "key") -> tuple[str, ...]:
    return tuple(
        i[campo] for i in itens or [] if isinstance(i, dict) and isinstance(i.get(campo), str)
    )


def edicao_de(dados: dict) -> EdicaoOL:
    brutos = list(dados.get("isbn_13") or []) + list(dados.get("isbn_10") or [])
    isbns = dict.fromkeys(n for b in brutos if isinstance(b, str) and (n := normalizar_isbn(b)))
    editoras = [e for e in dados.get("publishers") or [] if isinstance(e, str)]
    return EdicaoOL(
        chave=dados.get("key", ""),
        titulo=(dados.get("title") or "").strip(),
        works=_chaves(dados.get("works")),
        isbns=tuple(isbns),
        idiomas=tuple(k.rsplit("/", 1)[-1] for k in _chaves(dados.get("languages"))),
        traducao_de=(dados.get("translation_of") or "").strip() or None,
        titulos_da_obra=tuple(
            t.strip() for t in dados.get("work_titles") or [] if isinstance(t, str) and t.strip()
        ),
        ano=ano_de(dados.get("publish_date")),
        editora=editoras[0] if editoras else None,
        capa_url=_capa(dados),
    )


def obra_de(dados: dict) -> ObraOL:
    return ObraOL(
        chave=dados.get("key", ""),
        titulo=(dados.get("title") or "").strip(),
        descricao=texto_descricao(dados.get("description")),
        assuntos=tuple(assuntos(dados.get("subjects"))),
        ano=ano_de(dados.get("first_publish_date")),
        capa_url=_capa(dados),
    )


class OpenLibrary:
    """Cliente síncrono, seguro entre threads, com no máximo uma requisição por `intervalo`."""

    def __init__(
        self,
        user_agent: str,
        *,
        transporte: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        intervalo: float = 1.0,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(
            base_url=URL_BASE,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=timeout,
            transport=transporte,
            follow_redirects=True,
        )
        self._intervalo = intervalo
        self._relogio = relogio
        self._dormir = dormir
        self._trava = threading.Lock()
        self._ultima: float | None = None

    def fechar(self) -> None:
        self._http.close()

    def edicao_por_isbn(self, isbn13: str) -> EdicaoOL | None:
        dados = self._get(f"/isbn/{isbn13}.json")
        return edicao_de(dados) if dados else None

    def obra(self, chave: str) -> ObraOL | None:
        """A work de `chave` (/works/OL…W), seguindo os redirecionamentos de works fundidas."""
        for _ in range(_MAX_REDIRECIONAMENTOS + 1):
            dados = self._get(f"{chave}.json")
            if not dados:
                return None
            if (dados.get("type") or {}).get("key") != "/type/redirect":
                return obra_de(dados)
            chave = dados.get("location") or ""
            if not chave.startswith("/works/"):
                return None
        return None

    def _get(self, caminho: str) -> dict | None:
        with self._trava:
            if self._ultima is not None:
                espera = self._ultima + self._intervalo - self._relogio()
                if espera > 0:
                    self._dormir(espera)
            self._ultima = self._relogio()
            try:
                resposta = self._http.get(caminho)
            except httpx.HTTPError as e:
                raise FonteIndisponivel(f"Open Library: {e.__class__.__name__}") from e
        if resposta.status_code == 404:
            return None
        if resposta.status_code != 200:
            raise FonteIndisponivel(f"Open Library: HTTP {resposta.status_code} em {caminho}")
        try:
            dados = resposta.json()
        except ValueError as e:
            raise FonteIndisponivel(f"Open Library: resposta inválida em {caminho}") from e
        return dados if isinstance(dados, dict) else None
