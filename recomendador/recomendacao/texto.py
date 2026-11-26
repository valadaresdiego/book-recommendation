"""O texto de cada Obra que vira embedding (SPEC §8.2)."""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Connection, text

MAX_TAGS = 15  # tags de leitores, as de maior contagem
MAX_ASSUNTOS = 10  # assuntos da Open Library, depois das tags
MAX_DESCRICAO = 1500  # caracteres


@dataclass(frozen=True)
class DadosDaObra:
    titulo: str
    titulo_original: str | None = None
    autores: tuple[str, ...] = ()
    generos: tuple[str, ...] = ()  # da maior força para a menor
    tags: tuple[str, ...] = ()  # de leitores, da maior contagem para a menor
    assuntos: tuple[str, ...] = ()  # da Open Library
    descricao: str | None = None


def texto_da_obra(d: DadosDaObra) -> str:
    """`{titulo} ({titulo_original}). Autor: {autores}. Gêneros: {…}. Temas: {…}. {descrição}`

    O título original só entra se for diferente; as partes vazias saem. Os temas são até
    15 tags de leitores e até 10 assuntos da Open Library, em minúsculas e sem repetir.
    """
    titulo = d.titulo
    if d.titulo_original and d.titulo_original.strip() != d.titulo.strip():
        titulo += f" ({d.titulo_original.strip()})"
    partes = [titulo]
    if d.autores:
        partes.append("Autor: " + ", ".join(d.autores))
    if d.generos:
        partes.append("Gêneros: " + ", ".join(d.generos))
    if temas := _temas(d.tags, d.assuntos):
        partes.append("Temas: " + ", ".join(temas))
    texto = ". ".join(partes) + "."
    if d.descricao and (descricao := _cortar(d.descricao.strip(), MAX_DESCRICAO)):
        texto += " " + descricao
    return texto


def hash_do_texto(texto: str) -> str:
    """O SHA-256 do texto que virou o embedding (`obra.embedding_texto_hash`). Quando o texto
    da Obra muda (descrição, assuntos ou Gêneros novos), o hash deixa de bater (§10)."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _temas(tags: Iterable[str], assuntos: Iterable[str]) -> list[str]:
    vistos: dict[str, None] = {}
    for grupo, maximo in ((tags, MAX_TAGS), (assuntos, MAX_ASSUNTOS)):
        n = 0
        for bruto in grupo:
            tema = " ".join(bruto.replace("-", " ").lower().split())
            if tema and tema not in vistos and n < maximo:
                vistos[tema] = None
                n += 1
    return list(vistos)


def _cortar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    corte = texto[: limite - 1]
    if " " in corte:
        corte = corte[: corte.rfind(" ")]
    return corte.rstrip(" ,.;:") + "…"


_DADOS = text(
    """
    SELECT o.id, o.titulo, o.titulo_original, o.autores, o.descricao,
           coalesce((SELECT array_agg(g.nome ORDER BY og.forca DESC, g.nome)
                     FROM obra_genero og JOIN genero g ON g.id = og.genero_id
                     WHERE og.obra_id = o.id), '{}') AS generos,
           coalesce((SELECT array_agg(t.tag ORDER BY t.contagem DESC, t.tag)
                     FROM obra_tag t WHERE t.obra_id = o.id AND t.contagem > 0), '{}') AS tags,
           coalesce((SELECT array_agg(t.tag ORDER BY t.tag)
                     FROM obra_tag t WHERE t.obra_id = o.id AND t.contagem = 0), '{}') AS assuntos
    FROM obra o
    WHERE CAST(:ids AS bigint[]) IS NULL OR o.id = ANY(:ids)
    ORDER BY o.id
    """
)


def carregar_dados(conn: Connection, obra_ids: list[int] | None = None) -> dict[int, DadosDaObra]:
    """Os dados de texto das Obras pedidas (ou de todo o Catálogo), por id."""
    return {
        r.id: DadosDaObra(
            titulo=r.titulo,
            titulo_original=r.titulo_original,
            autores=tuple(r.autores),
            generos=tuple(r.generos),
            tags=tuple(r.tags),
            assuntos=tuple(r.assuntos),
            descricao=r.descricao,
        )
        for r in conn.execute(_DADOS, {"ids": obra_ids})
    }
