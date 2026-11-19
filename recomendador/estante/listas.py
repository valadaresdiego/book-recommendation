"""Dispensa (R7) e Quero ler (R8), da fase 4 (SPEC §8.6), e Estou lendo (R13), da fase 5
(§8.7, ADR 0008).

Uma Obra fica em no máximo uma das três: entrar numa lista tira das outras duas e desfaz a
Dispensa, e dispensar tira das listas. A consulta de "Para você" exclui as três das
candidatas.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from recomendador.estante.eventos import registrar_evento
from recomendador.estante.leituras import JaNaEstante, leitura_da_obra


@dataclass(frozen=True)
class ItemDeLista:
    obra_id: int
    titulo: str  # `titulo_exibicao`
    autores: tuple[str, ...]
    capa_url: str | None
    posicao: int | None  # posição em "Para você" quando foi salva; nula fora de lá
    criado_em: datetime  # quando entrou na lista


@dataclass(frozen=True)
class ItemQueroLer(ItemDeLista):
    """Uma Obra da lista Quero ler (R8)."""


@dataclass(frozen=True)
class ItemEstouLendo(ItemDeLista):
    """Uma Obra da lista Estou lendo (R13); `criado_em` é quando o Leitor começou."""


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


def _posicao(conn: Connection, tabela: str, leitor_id: uuid.UUID, obra_id: int) -> int | None:
    return conn.execute(
        text(f"SELECT posicao FROM {tabela} WHERE leitor_id = :l AND obra_id = :o"),
        {"l": leitor_id, "o": obra_id},
    ).scalar_one_or_none()


def _listar(conn: Connection, tabela: str, leitor_id: uuid.UUID, classe: type) -> list:
    """Uma lista, da Obra que entrou mais recentemente para a mais antiga."""
    linhas = conn.execute(
        text(
            f"""
            SELECT q.obra_id, o.titulo_exibicao AS titulo, o.autores, o.capa_url,
                   q.posicao, q.criado_em
            FROM {tabela} q JOIN obra o ON o.id = q.obra_id
            WHERE q.leitor_id = :l
            ORDER BY q.criado_em DESC, q.obra_id DESC
            """
        ),
        {"l": leitor_id},
    )
    return [classe(**{**r._mapping, "autores": tuple(r.autores or ())}) for r in linhas]


# --- Dispensa (R7) ---


def dispensar(
    conn: Connection,
    leitor_id: uuid.UUID,
    obra_id: int,
    posicao: int | None = None,
    lista: str | None = None,
) -> None:
    """A Obra não volta a "Para você". Sai também de Quero ler e de Estou lendo.

    `posicao` é a posição em "Para você", e `lista` a lista de onde ela veio (`geral` ou
    `tecnologia`), para o O2 (evento `sugestao_dispensada`, SPEC §7.6 e §8.8).
    """
    conn.execute(
        text("INSERT INTO dispensa (leitor_id, obra_id) VALUES (:l, :o) ON CONFLICT DO NOTHING"),
        {"l": leitor_id, "o": obra_id},
    )
    _apagar(conn, "quero_ler", leitor_id, obra_id)
    _apagar(conn, "estou_lendo", leitor_id, obra_id)
    registrar_evento(conn, leitor_id, "sugestao_dispensada", obra_id, posicao=posicao, lista=lista)


def desfazer_dispensa(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> None:
    _apagar(conn, "dispensa", leitor_id, obra_id)


def dispensada(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> bool:
    return _existe(conn, "dispensa", leitor_id, obra_id)


# --- Quero ler (R8) ---


def salvar_quero_ler(
    conn: Connection,
    leitor_id: uuid.UUID,
    obra_id: int,
    posicao: int | None = None,
    lista: str | None = None,
) -> None:
    """Põe a Obra na lista Quero ler, tira de Estou lendo e desfaz uma Dispensa dela.

    `posicao` é a posição em "Para você" (O2 e O5); salvar de novo mantém a primeira. Sem
    ela, vale a que a Obra tinha em Estou lendo. `lista` é a lista de "Para você" de onde a
    Obra veio (O2, §8.8). Levanta `JaNaEstante` se a Obra já for uma Leitura.
    """
    if existente := leitura_da_obra(conn, leitor_id, obra_id):
        raise JaNaEstante(existente)
    if posicao is None:
        posicao = _posicao(conn, "estou_lendo", leitor_id, obra_id)
    conn.execute(
        text(
            "INSERT INTO quero_ler (leitor_id, obra_id, posicao) VALUES (:l, :o, :p) "
            "ON CONFLICT DO NOTHING"
        ),
        {"l": leitor_id, "o": obra_id, "p": posicao},
    )
    _apagar(conn, "dispensa", leitor_id, obra_id)
    _apagar(conn, "estou_lendo", leitor_id, obra_id)
    registrar_evento(conn, leitor_id, "quero_ler_salvo", obra_id, posicao=posicao, lista=lista)


def tirar_de_quero_ler(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> None:
    """Tira a Obra da lista. "Já li" faz o mesmo, dentro de `adicionar`."""
    _apagar(conn, "quero_ler", leitor_id, obra_id)


def na_lista_quero_ler(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> bool:
    return _existe(conn, "quero_ler", leitor_id, obra_id)


def listar_quero_ler(conn: Connection, leitor_id: uuid.UUID) -> list[ItemQueroLer]:
    """A lista Quero ler, da Obra salva mais recentemente para a mais antiga."""
    return _listar(conn, "quero_ler", leitor_id, ItemQueroLer)


# --- Estou lendo (R13) ---


def salvar_estou_lendo(
    conn: Connection, leitor_id: uuid.UUID, obra_id: int, posicao: int | None = None
) -> None:
    """ "Comecei a ler": põe a Obra em Estou lendo, tira de Quero ler e desfaz a Dispensa.

    `posicao` é a posição em "Para você". Sem ela, vale a que a Obra tinha em Quero ler,
    para o "Já li" ainda contar no O5. Salvar de novo mantém a primeira. Levanta
    `JaNaEstante` se a Obra já for uma Leitura (sem releitura na v1, ADR 0008).
    """
    if existente := leitura_da_obra(conn, leitor_id, obra_id):
        raise JaNaEstante(existente)
    if posicao is None:
        posicao = _posicao(conn, "quero_ler", leitor_id, obra_id)
    conn.execute(
        text(
            "INSERT INTO estou_lendo (leitor_id, obra_id, posicao) VALUES (:l, :o, :p) "
            "ON CONFLICT DO NOTHING"
        ),
        {"l": leitor_id, "o": obra_id, "p": posicao},
    )
    _apagar(conn, "quero_ler", leitor_id, obra_id)
    _apagar(conn, "dispensa", leitor_id, obra_id)
    registrar_evento(conn, leitor_id, "leitura_iniciada", obra_id, posicao=posicao)


def tirar_de_estou_lendo(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> None:
    """ "Parei de ler". "Já li" também tira a Obra da lista, dentro de `adicionar`."""
    _apagar(conn, "estou_lendo", leitor_id, obra_id)


def na_lista_estou_lendo(conn: Connection, leitor_id: uuid.UUID, obra_id: int) -> bool:
    return _existe(conn, "estou_lendo", leitor_id, obra_id)


def listar_estou_lendo(conn: Connection, leitor_id: uuid.UUID) -> list[ItemEstouLendo]:
    """A lista Estou lendo, da Obra começada mais recentemente para a mais antiga."""
    return _listar(conn, "estou_lendo", leitor_id, ItemEstouLendo)
