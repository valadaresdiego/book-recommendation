"""Cliente da busca do Google Books (R1, SPEC §5 e §7.1).

Os termos do Google não permitem cópia permanente: o que vem daqui serve à busca e, quando o
Leitor escolhe uma Edição, só os dados dela vão para o banco: a Edição (com a capa por URL)
em `edicao` e, numa Obra do Leitor, as categorias em `obra_tag` (SPEC §6.3).
"""

import re

import httpx

from recomendador.catalogo.fontes import FonteIndisponivel
from recomendador.catalogo.isbn import normalizar_isbn, parece_isbn
from recomendador.catalogo.texto import separar_editora
from recomendador.catalogo.tipos import ResultadoBusca

URL = "https://www.googleapis.com/books/v1/volumes"
MAX_RESULTADOS = 20
# Só os campos usados: a resposta fica bem menor.
_CAMPOS_DO_VOLUME = (
    "id,volumeInfo(title,subtitle,authors,publisher,publishedDate,description,"
    "industryIdentifiers,imageLinks,language,categories)"
)
_CAMPOS = f"items({_CAMPOS_DO_VOLUME})"
_RE_ANO = re.compile(r"^(\d{4})")


def montar_q(texto: str) -> str:
    """ISBN de 10 ou 13 dígitos (com ou sem hífens) vira `isbn:…`; `editora:x` vira
    `inpublisher:x`; o resto vai como texto."""
    texto = " ".join(texto.split())
    livre, editora = separar_editora(texto)
    if editora:
        filtro = f'inpublisher:"{editora}"' if " " in editora else f"inpublisher:{editora}"
        return f"{livre} {filtro}".strip()
    if parece_isbn(livre):
        return "isbn:" + re.sub(r"[\s\-]", "", livre).upper()
    return livre


def _capa(volume: dict) -> str | None:
    links = volume.get("imageLinks") or {}
    url = links.get("thumbnail") or links.get("smallThumbnail")
    if not isinstance(url, str):
        return None
    return "https://" + url.removeprefix("http://").removeprefix("https://")


def _resultado(item: dict) -> ResultadoBusca | None:
    v = item.get("volumeInfo") or {}
    titulo = (v.get("title") or "").strip()
    if not titulo or not item.get("id"):
        return None
    isbns = dict.fromkeys(
        n
        for i in v.get("industryIdentifiers") or []
        if isinstance(i, dict)
        and i.get("type") in ("ISBN_13", "ISBN_10")
        and (n := normalizar_isbn(i.get("identifier")))
    )
    ano = _RE_ANO.match(v.get("publishedDate") or "")
    idioma = (v.get("language") or "").split("-")[0].lower() or None
    return ResultadoBusca(
        titulo=titulo,
        autores=tuple(a.strip() for a in v.get("authors") or [] if a.strip()),
        ano=int(ano.group(1)) if ano else None,
        capa_url=_capa(v),
        google_volume_id=item["id"],
        isbns=tuple(isbns),
        editora=(v.get("publisher") or "").strip() or None,
        idioma=idioma,
        descricao=(v.get("description") or "").strip() or None,
        categorias=tuple(
            c.strip() for c in v.get("categories") or [] if isinstance(c, str) and c.strip()
        ),
    )


class GoogleBooks:
    def __init__(
        self,
        api_key: str,
        *,
        transporte: httpx.BaseTransport | None = None,
        timeout: float = 4.0,
    ) -> None:
        # Em 19/11/2026, buscas de livros técnicos levaram de 1,8 a 2,3 s: com 1,8 s o app
        # desistia delas. A meta de 2 s vale para o Catálogo; o Google Books tem até 4 s (§7.1).
        self._chave = api_key
        self._http = httpx.Client(timeout=timeout, transport=transporte)

    def fechar(self) -> None:
        self._http.close()

    def _get(self, url: str, params: dict) -> dict:
        if self._chave:
            params["key"] = self._chave
        try:
            resposta = self._http.get(url, params=params)
        except httpx.HTTPError as e:
            # Sem a URL na mensagem: ela leva a chave da API.
            raise FonteIndisponivel(f"Google Books: {e.__class__.__name__}") from None
        if resposta.status_code != 200:
            raise FonteIndisponivel(f"Google Books: HTTP {resposta.status_code}")
        try:
            dados = resposta.json()
        except ValueError as e:
            raise FonteIndisponivel("Google Books: resposta inválida") from e
        return dados if isinstance(dados, dict) else {}

    def buscar(self, texto: str) -> list[ResultadoBusca]:
        params = {
            "q": montar_q(texto),
            "maxResults": MAX_RESULTADOS,
            "printType": "books",
            "fields": _CAMPOS,
        }
        itens = self._get(URL, params).get("items") or []
        return [r for i in itens if isinstance(i, dict) and (r := _resultado(i))]

    def volume(self, volume_id: str) -> ResultadoBusca | None:
        """A Edição de um volume já escolhido (as categorias das Edições gravadas antes)."""
        return _resultado(self._get(f"{URL}/{volume_id}", {"fields": _CAMPOS_DO_VOLUME}))
