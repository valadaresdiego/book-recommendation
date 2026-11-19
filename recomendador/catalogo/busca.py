"""Busca do R1 (SPEC §7.1): Catálogo local e Google Books em paralelo, fundidos pelo ISBN."""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from sqlalchemy import Connection, text

from recomendador.catalogo.fontes import FonteIndisponivel
from recomendador.catalogo.fontes.google_books import GoogleBooks
from recomendador.catalogo.isbn import normalizar_isbn, parece_isbn
from recomendador.catalogo.texto import palavras_da_busca, separar_editora
from recomendador.catalogo.tipos import ResultadoBusca

log = logging.getLogger(__name__)

LIMITE_LOCAL = 10
# Média mínima, entre as palavras da busca, da semelhança de cada palavra com a Obra.
SEMELHANCA_MINIMA = 0.5

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="google-books")


@dataclass(frozen=True)
class Busca:
    resultados: list[ResultadoBusca]
    google_indisponivel: bool = False  # o Google Books não respondeu a tempo


_TEXTO = "obra_texto_busca(o.titulo, o.titulo_original, o.titulo_exibicao, o.autores)"

# Cada palavra é comparada (word_similarity) com títulos e autores da Obra num texto só, sem
# acento. A semelhança da Obra é a média entre as palavras: "duna herbert" precisa casar com
# as duas, e "herbert" sozinho (David Herbert Donald) fica abaixo.
_POR_TEXTO = text(
    f"""
    WITH palavras AS (SELECT unnest(CAST(:palavras AS text[])) AS p),
    alvo AS (
        SELECT DISTINCT o.id FROM obra o JOIN palavras ON palavras.p <% {_TEXTO}
    ),
    pontuadas AS (
        SELECT o.id, avg(word_similarity(palavras.p, {_TEXTO})) AS semelhanca
        FROM obra o JOIN alvo USING (id) CROSS JOIN palavras
        GROUP BY o.id
    )
    SELECT o.id, o.titulo_exibicao, o.autores, o.ano_original, o.capa_url
    FROM pontuadas p JOIN obra o USING (id)
    WHERE p.semelhanca >= :minima
    ORDER BY p.semelhanca DESC, o.popularidade DESC, o.id
    LIMIT :limite
    """
)

_POR_ISBN = text(
    """
    SELECT o.id, o.titulo_exibicao, o.autores, o.ano_original, o.capa_url
    FROM obra_isbn i JOIN obra o ON o.id = i.obra_id
    WHERE i.isbn13 = :isbn
    """
)

_POR_IDS = text(
    """
    SELECT o.id, o.titulo_exibicao, o.autores, o.ano_original, o.capa_url
    FROM obra o WHERE o.id = ANY(:ids)
    """
)


def _da_obra(linha) -> ResultadoBusca:
    return ResultadoBusca(
        titulo=linha.titulo_exibicao,
        autores=tuple(linha.autores or ()),
        ano=linha.ano_original,
        capa_url=linha.capa_url,
        obra_id=linha.id,
    )


def buscar_no_catalogo(
    conn: Connection,
    texto: str,
    limite: int = LIMITE_LOCAL,
    minima: float = SEMELHANCA_MINIMA,
) -> list[ResultadoBusca]:
    """Obras do Catálogo por ISBN (igualdade em `obra_isbn`) e por trigram de títulos e autores.

    Com `minima=0`, devolve as `limite` mais próximas que casam com ao menos uma palavra.
    """
    resultados: dict[int, ResultadoBusca] = {}
    if parece_isbn(texto) and (isbn := normalizar_isbn(texto)):
        for linha in conn.execute(_POR_ISBN, {"isbn": isbn}):
            resultados[linha.id] = _da_obra(linha)
    if palavras := palavras_da_busca(texto):
        parametros = {"palavras": palavras, "minima": minima, "limite": limite}
        for linha in conn.execute(_POR_TEXTO, parametros):
            resultados.setdefault(linha.id, _da_obra(linha))
    return list(resultados.values())[:limite]


def _fundida(edicao: ResultadoBusca, obra: ResultadoBusca) -> ResultadoBusca:
    """A Edição do Google Books ligada à Obra do Catálogo que tem o ISBN dela."""
    return replace(
        edicao,
        obra_id=obra.obra_id,
        capa_url=edicao.capa_url or obra.capa_url,
        titulo_obra=obra.titulo if obra.titulo != edicao.titulo else None,
    )


def _fundir(
    conn: Connection, locais: list[ResultadoBusca], do_google: list[ResultadoBusca]
) -> list[ResultadoBusca]:
    isbns = [i for r in do_google for i in r.isbns]
    obra_por_isbn = (
        dict(
            conn.execute(
                text("SELECT isbn13, obra_id FROM obra_isbn WHERE isbn13 = ANY(:i)"), {"i": isbns}
            ).all()
        )
        if isbns
        else {}
    )
    catalogo = {r.obra_id: r for r in locais}
    fora_da_busca = {
        o
        for r in do_google
        for i in r.isbns
        if (o := obra_por_isbn.get(i)) not in (None, *catalogo)
    }
    extras = (
        {
            linha.id: _da_obra(linha)
            for linha in conn.execute(_POR_IDS, {"ids": list(fora_da_busca)})
        }
        if fora_da_busca
        else {}
    )

    # Uma Edição em português toma o lugar do item do Catálogo (é o título que o Leitor
    # reconhece); em outro idioma, o item do Catálogo fica como está, sem repetir a Obra.
    fundidas: dict[int, ResultadoBusca] = {}
    so_google: list[ResultadoBusca] = []
    for r in do_google:
        obra_id = next((obra_por_isbn[i] for i in r.isbns if i in obra_por_isbn), None)
        if obra_id is None:
            so_google.append(r)
            continue
        obra = catalogo.get(obra_id) or extras[obra_id]
        atual = fundidas.get(obra_id)
        if r.idioma == "pt" and (atual is None or atual.google_volume_id is None):
            fundidas[obra_id] = _fundida(r, obra)
        elif atual is None:
            fundidas[obra_id] = obra

    no_catalogo = [fundidas.get(r.obra_id, r) for r in locais]
    no_catalogo += [fundidas[o] for o in fundidas if o not in catalogo]
    return no_catalogo + so_google


def buscar(conn: Connection, texto: str, google: GoogleBooks | None) -> Busca:
    """Catálogo primeiro, depois o Google Books. Sem `google`, só o Catálogo.

    Se o Google Books não responder a tempo, devolve só o Catálogo e marca
    `google_indisponivel`, para a UI mostrar um aviso discreto.

    Com o filtro `editora:`, só o Google Books busca: o Catálogo não sabe a editora das
    Obras. As Edições que ele trouxer e cujo ISBN está no Catálogo continuam fundidas.
    """
    texto = " ".join(texto.split())
    livre, editora = separar_editora(texto)
    if not livre and not editora:
        return Busca([])
    pedido = _executor.submit(google.buscar, texto) if google else None
    locais = [] if editora else buscar_no_catalogo(conn, livre)
    if pedido is None:
        return Busca(locais)
    try:
        do_google = pedido.result()
    except FonteIndisponivel as e:
        log.warning("Busca sem o Google Books: %s", e)
        return Busca(locais, google_indisponivel=True)
    return Busca(_fundir(conn, locais, do_google))
