"""Leituras e Notas do Leitor (R1 a R3, SPEC §7.3 e §7.5)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Connection, text

from recomendador.estante.eventos import registrar_evento

OrigemLeitura = Literal["busca", "montagem", "sugestao", "manual", "catalogo"]
OrdemEstante = Literal["nota", "data"]


@dataclass(frozen=True)
class Leitura:
    id: int
    obra_id: int
    nota: int | None
    origem: str
    edicao_id: int | None


@dataclass(frozen=True)
class ItemEstante:
    """Uma Leitura como a Estante mostra: capa, `titulo_exibicao`, autor e Nota."""

    leitura_id: int
    obra_id: int
    titulo: str
    autores: tuple[str, ...]
    nota: int | None
    capa_url: str | None  # a da Edição escolhida, se houver; senão a da Obra
    origem: str
    criado_em: datetime


class JaNaEstante(Exception):
    """A Obra já está na Estante (UNIQUE leitor_id, obra_id): o R1 avisa e não duplica."""

    def __init__(self, item: ItemEstante) -> None:
        self.item = item
        nota = f"com nota {item.nota}" if item.nota else "sem nota"
        super().__init__(f"Você já tem {item.titulo} na Estante, {nota}")


def _validar_nota(nota: int | None) -> None:
    if nota is not None and not 1 <= nota <= 5:
        raise ValueError(f"A Nota vai de 1 a 5 (recebida: {nota})")


_ITENS = """
    SELECT l.id AS leitura_id, l.obra_id, o.titulo_exibicao AS titulo, o.autores, l.nota,
           coalesce(e.capa_url, o.capa_url) AS capa_url, l.origem, l.criado_em
    FROM leitura l
    JOIN obra o ON o.id = l.obra_id
    LEFT JOIN edicao e ON e.id = l.edicao_id
    WHERE l.leitor_id = :leitor
"""

_ORDEM = {
    "nota": "l.nota DESC NULLS LAST, l.criado_em DESC, l.id DESC",
    "data": "l.criado_em DESC, l.id DESC",
}


def _item(linha) -> ItemEstante:
    return ItemEstante(**{**linha._mapping, "autores": tuple(linha.autores or ())})


def listar(conn: Connection, leitor_id: uuid.UUID, ordem: OrdemEstante = "data") -> list:
    """A Estante, por Nota (sem Nota no fim) ou por data de inclusão, decrescente."""
    sql = f"{_ITENS} ORDER BY {_ORDEM[ordem]}"
    return [_item(linha) for linha in conn.execute(text(sql), {"leitor": leitor_id})]


def leitura_da_obra(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> ItemEstante | None:
    linha = conn.execute(
        text(f"{_ITENS} AND l.obra_id = :obra"), {"leitor": leitor_id, "obra": obra_id}
    ).one_or_none()
    return _item(linha) if linha else None


def contar_notas(conn: Connection, leitor_id: uuid.UUID) -> int:
    """Leituras com Nota: as únicas que contam para as Sugestões e para a Montagem."""
    return conn.execute(
        text("SELECT count(*) FROM leitura WHERE leitor_id = :l AND nota IS NOT NULL"),
        {"l": leitor_id},
    ).scalar_one()


def adicionar(
    conn: Connection,
    leitor_id: uuid.UUID,
    obra_id: int,
    nota: int | None,
    *,
    origem: OrigemLeitura,
    edicao_id: int | None = None,
    duracao_s: float | None = None,
) -> Leitura:
    """Põe a Obra na Estante. A Nota pode ficar vazia (R2): a Leitura fica fora das Sugestões.

    `duracao_s` é o tempo desde a última busca da sessão, para o O3 (evento `leitura_salva`).
    Levanta `JaNaEstante` se a Obra já estiver lá, mesmo por outra Edição. A Obra sai da
    lista Quero ler (R8, SPEC §8.6).

    O embedding de uma Obra `origem='leitor'` (SPEC §7.3) é calculado depois, numa
    transação à parte (`recomendacao.calcular_vizinhos_da_obra`), para uma falha nele não
    desfazer a Leitura.
    """
    _validar_nota(nota)
    if existente := leitura_da_obra(conn, leitor_id, obra_id):
        raise JaNaEstante(existente)
    linha = conn.execute(
        text(
            """
            INSERT INTO leitura (leitor_id, obra_id, edicao_id, nota, origem)
            VALUES (:leitor, :obra, :edicao, :nota, :origem)
            RETURNING id, obra_id, nota, origem, edicao_id
            """
        ),
        {"leitor": leitor_id, "obra": obra_id, "edicao": edicao_id, "nota": nota, "origem": origem},
    ).one()
    conn.execute(
        text("DELETE FROM quero_ler WHERE leitor_id = :l AND obra_id = :o"),
        {"l": leitor_id, "o": obra_id},
    )
    registrar_evento(
        conn,
        leitor_id,
        "leitura_salva",
        obra_id,
        origem=origem,
        duracao_s=duracao_s,
        com_nota=nota is not None,
    )
    return Leitura(**linha._mapping)


def mudar_nota(conn: Connection, leitor_id: uuid.UUID, obra_id: int, nota: int | None) -> None:
    """Muda a Nota (R2). As Sugestões são calculadas na leitura, então nada mais é recalculado."""
    _validar_nota(nota)
    de = conn.execute(
        text(
            """
            UPDATE leitura l SET nota = :nota, atualizado_em = now()
            FROM leitura antes
            WHERE antes.id = l.id AND l.leitor_id = :leitor AND l.obra_id = :obra
            RETURNING antes.nota
            """
        ),
        {"leitor": leitor_id, "obra": obra_id, "nota": nota},
    ).one_or_none()
    if de is None:
        raise LookupError(f"A Obra {obra_id} não está na Estante")
    if de.nota != nota:
        registrar_evento(conn, leitor_id, "nota_alterada", obra_id, de=de.nota, para=nota)


def remover(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> None:
    """Tira a Obra da Estante (R2): ela volta a poder ser sugerida."""
    nota = conn.execute(
        text("DELETE FROM leitura WHERE leitor_id = :l AND obra_id = :o RETURNING nota"),
        {"l": leitor_id, "o": obra_id},
    ).one_or_none()
    if nota is None:
        raise LookupError(f"A Obra {obra_id} não está na Estante")
    registrar_evento(conn, leitor_id, "leitura_removida", obra_id, nota=nota.nota)
