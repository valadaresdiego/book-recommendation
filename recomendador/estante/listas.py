"""Dispensa (R7) e Quero ler (R8), da fase 4 (SPEC §8.6).

Uma Obra fica em no máximo uma das duas: salvar em Quero ler desfaz a Dispensa, e
dispensar tira da lista. A consulta de "Para você" exclui as duas das candidatas.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from recomendador.estante.eventos import registrar_evento
from recomendador.estante.leituras import JaNaEstante, leitura_da_obra


@dataclass(frozen=True)
class ItemQueroLer:
    obra_id: int
    titulo: str  # `titulo_exibicao`
    autores: tuple[str, ...]
    capa_url: str | None
    posicao: int | None  # posição em "Para você" quando foi salva; nula fora de lá
    criado_em: datetime


def _apagar(conn: Connection, tabela: str, leitor_id: uuid.UUID, obra_id: int) -> None:
    conn.execute(
        text(f"DELETE FROM {tabela} WHERE leitor_id = :l AND obra_id = :o"),
        {"l": leitor_id, "o": obra_id},
    )


def _existe(conn: Connection, tabela: str, leitor_id: uuid.UUID, obra_id: int) -> bool:
    return conn.execute(
        text(f"SELECT EXISTS (SELECT 1 FROM {tabela} WHERE leitor_id = :l AND obra_id = :o)"),
        {"l": leitor_id, "o": obra_id},
    ).scalar_one()


# --- Dispensa (R7) ---


def dispensar(
    conn: Connection, leitor_id: uuid.UUID, obra_id: int, posicao: int | None = None
) -> None:
    """A Obra não volta a "Para você". Sai também de Quero ler.

    `posicao` é a posição em "Para você", para o O2 (evento `sugestao_dispensada`).
    """
    conn.execute(
        text("INSERT INTO dispensa (leitor_id, obra_id) VALUES (:l, :o) ON CONFLICT DO NOTHING"),
        {"l": leitor_id, "o": obra_id},
    )
    _apagar(conn, "quero_ler", leitor_id, obra_id)
    registrar_evento(conn, leitor_id, "sugestao_dispensada", obra_id, posicao=posicao)


def desfazer_dispensa(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> None:
    _apagar(conn, "dispensa", leitor_id, obra_id)


def dispensada(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> bool:
    return _existe(conn, "dispensa", leitor_id, obra_id)


# --- Quero ler (R8) ---


def salvar_quero_ler(
    conn: Connection, leitor_id: uuid.UUID, obra_id: int, posicao: int | None = None
) -> None:
    """Põe a Obra na lista Quero ler e desfaz uma Dispensa dela.

    `posicao` é a posição em "Para você" (O2 e O5); salvar de novo mantém a primeira.
    Levanta `JaNaEstante` se a Obra já for uma Leitura.
    """
    if existente := leitura_da_obra(conn, leitor_id, obra_id):
        raise JaNaEstante(existente)
    conn.execute(
        text(
            "INSERT INTO quero_ler (leitor_id, obra_id, posicao) VALUES (:l, :o, :p) "
            "ON CONFLICT DO NOTHING"
        ),
        {"l": leitor_id, "o": obra_id, "p": posicao},
    )
    _apagar(conn, "dispensa", leitor_id, obra_id)
    registrar_evento(conn, leitor_id, "quero_ler_salvo", obra_id, posicao=posicao)


def tirar_de_quero_ler(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> None:
    """Tira a Obra da lista. "Já li" faz o mesmo, dentro de `adicionar`."""
    _apagar(conn, "quero_ler", leitor_id, obra_id)


def na_lista_quero_ler(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> bool:
    return _existe(conn, "quero_ler", leitor_id, obra_id)


def listar_quero_ler(conn: Connection, leitor_id: uuid.UUID) -> list[ItemQueroLer]:
    """A lista Quero ler, da Obra salva mais recentemente para a mais antiga."""
    linhas = conn.execute(
        text(
            """
            SELECT q.obra_id, o.titulo_exibicao AS titulo, o.autores, o.capa_url,
                   q.posicao, q.criado_em
            FROM quero_ler q JOIN obra o ON o.id = q.obra_id
            WHERE q.leitor_id = :l
            ORDER BY q.criado_em DESC, q.obra_id DESC
            """
        ),
        {"l": leitor_id},
    )
    return [ItemQueroLer(**{**r._mapping, "autores": tuple(r.autores or ())}) for r in linhas]
