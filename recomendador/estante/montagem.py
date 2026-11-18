"""Montagem da Estante (R12, SPEC §7.4): Gêneros de interesse e uma grade de Obras populares."""

import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import Connection, text

from recomendador.estante.eventos import evento_registrado, registrar_evento
from recomendador.estante.leituras import contar_notas

NOTAS_PARA_SUGESTOES = 5  # O1: com 5 Notas, ≥ 10 Sugestões
OBRAS_POR_PAGINA = 24


@dataclass(frozen=True)
class CardMontagem:
    obra_id: int
    titulo: str
    autores: tuple[str, ...]
    capa_url: str | None
    genero: str  # slug do Gênero escolhido que trouxe a Obra


def montagem_pendente(conn: Connection, leitor_id: uuid.UUID) -> bool:
    """A Montagem abre sozinha enquanto há menos de 5 Notas e o Leitor não clicou em "Pular"."""
    return contar_notas(conn, leitor_id) < NOTAS_PARA_SUGESTOES and not evento_registrado(
        conn, leitor_id, "montagem_pulada"
    )


def pular_montagem(conn: Connection, leitor_id: uuid.UUID) -> None:
    registrar_evento(conn, leitor_id, "montagem_pulada")


# Dentro de cada Gênero, por popularidade × força; entre os Gêneros, round-robin na ordem
# escolhida. Uma Obra de dois Gêneros escolhidos aparece só na primeira vez.
_GRADE = text(
    """
    WITH escolhidos AS (
        SELECT g.id, g.slug, e.posicao
        FROM unnest(CAST(:generos AS text[])) WITH ORDINALITY AS e(slug, posicao)
        JOIN genero g ON g.slug = e.slug
    ),
    por_genero AS (
        SELECT og.obra_id, e.slug, e.posicao,
               row_number() OVER (
                   PARTITION BY e.id ORDER BY o.popularidade * og.forca DESC, o.id
               ) AS ordem
        FROM escolhidos e
        JOIN obra_genero og ON og.genero_id = e.id
        JOIN obra o ON o.id = og.obra_id
        WHERE o.origem = 'base'
          AND o.id <> ALL(CAST(:excluir AS bigint[]))
          AND NOT EXISTS (
              SELECT 1 FROM leitura l WHERE l.leitor_id = :leitor AND l.obra_id = o.id
          )
    ),
    primeira_vez AS (
        SELECT DISTINCT ON (obra_id) obra_id, slug, posicao, ordem
        FROM por_genero ORDER BY obra_id, ordem, posicao
    )
    SELECT o.id AS obra_id, o.titulo_exibicao AS titulo, o.autores, o.capa_url, p.slug AS genero
    FROM primeira_vez p JOIN obra o ON o.id = p.obra_id
    ORDER BY p.ordem, p.posicao
    LIMIT :limite
    """
)


def grade_da_montagem(
    conn: Connection,
    leitor_id: uuid.UUID,
    generos: list[str],
    excluir: Collection[int] = (),
    limite: int = OBRAS_POR_PAGINA,
) -> list[CardMontagem]:
    """As próximas Obras da grade, fora da Estante e de `excluir` (já mostradas ou "Não li")."""
    if not generos:
        return []
    linhas = conn.execute(
        _GRADE,
        {"generos": generos, "excluir": list(excluir), "leitor": leitor_id, "limite": limite},
    )
    return [
        CardMontagem(**{**linha._mapping, "autores": tuple(linha.autores or ())})
        for linha in linhas
    ]
