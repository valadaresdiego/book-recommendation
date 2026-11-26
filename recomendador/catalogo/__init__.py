"""Catálogo: busca (R1), resolução Edição → Obra (SPEC §7.2), ISBN, tags e Gêneros.

O `app/` usa só o que está exportado aqui. A carga e o enriquecimento em lote ficam em
`recomendador.pipeline`.
"""

from functools import cache

from recomendador.catalogo.busca import Busca, buscar, buscar_no_catalogo
from recomendador.catalogo.capas import capa, capa_reserva
from recomendador.catalogo.fontes.google_books import GoogleBooks
from recomendador.catalogo.fontes.open_library import OpenLibrary
from recomendador.catalogo.generos import SLUG_TECNOLOGIA, GeneroDoCatalogo, listar_generos
from recomendador.catalogo.resolucao import (
    ObraRegistrada,
    informar_titulo_original,
    registrar_isbns,
    registrar_resolucao,
    resolver_manual,
    resolver_obra,
)
from recomendador.catalogo.tipos import Candidata, ObraProposta, Resolucao, ResultadoBusca
from recomendador.config import config
from recomendador.db.sessao import transacao


@cache
def google_books() -> GoogleBooks | None:
    """O cliente do processo; None se a chave da API não estiver no `.env`."""
    chave = config().google_books_api_key
    return GoogleBooks(chave) if chave else None


@cache
def open_library() -> OpenLibrary:
    """O cliente do processo, com o limitador de 1 req/s compartilhado entre as páginas."""
    return OpenLibrary(config().open_library_user_agent)


__all__ = [
    "SLUG_TECNOLOGIA",
    "Busca",
    "Candidata",
    "GeneroDoCatalogo",
    "ObraProposta",
    "ObraRegistrada",
    "Resolucao",
    "ResultadoBusca",
    "buscar",
    "buscar_no_catalogo",
    "capa",
    "capa_reserva",
    "google_books",
    "informar_titulo_original",
    "listar_generos",
    "open_library",
    "registrar_isbns",
    "registrar_resolucao",
    "resolver_manual",
    "resolver_obra",
    "transacao",
]
