"""Dispensa (R7) e Quero ler (R8), da fase 4 (SPEC §8.6), contra o banco real."""

import pytest
from fabricas import criar_obra
from sqlalchemy import Connection, text

from recomendador.config import LEITOR_ID
from recomendador.estante import (
    JaNaEstante,
    adicionar,
    desfazer_dispensa,
    dispensada,
    dispensar,
    listar_quero_ler,
    na_lista_quero_ler,
    salvar_quero_ler,
    tirar_de_quero_ler,
)


def _eventos(conexao: Connection, tipo: str) -> list[tuple[int, dict]]:
    return [
        tuple(r)
        for r in conexao.execute(
            text("SELECT obra_id, dados FROM evento WHERE tipo = :t ORDER BY id"), {"t": tipo}
        )
    ]


@pytest.fixture
def duna(conexao: Connection) -> int:
    return criar_obra(conexao, "Dune", ("Frank Herbert",), titulo_exibicao="Duna")


@pytest.fixture
def fundacao(conexao: Connection) -> int:
    return criar_obra(conexao, "Foundation", ("Isaac Asimov",), titulo_exibicao="Fundação")


# --- Dispensa (R7) ---


def test_dispensar_grava_e_registra_o_evento(conexao, duna) -> None:
    dispensar(conexao, LEITOR_ID, duna, posicao=3)
    dispensar(conexao, LEITOR_ID, duna, posicao=3)  # repetir não duplica

    assert dispensada(conexao, LEITOR_ID, duna)
    assert conexao.execute(text("SELECT count(*) FROM dispensa")).scalar_one() == 1
    assert _eventos(conexao, "sugestao_dispensada")[0] == (duna, {"posicao": 3})


def test_desfazer_a_dispensa(conexao, duna) -> None:
    dispensar(conexao, LEITOR_ID, duna)
    desfazer_dispensa(conexao, LEITOR_ID, duna)
    assert not dispensada(conexao, LEITOR_ID, duna)


def test_dispensar_tira_de_quero_ler(conexao, duna) -> None:
    salvar_quero_ler(conexao, LEITOR_ID, duna)
    dispensar(conexao, LEITOR_ID, duna)
    assert not na_lista_quero_ler(conexao, LEITOR_ID, duna)


# --- Quero ler (R8) ---


def test_salvar_em_quero_ler_lista_da_mais_recente(conexao, duna, fundacao) -> None:
    salvar_quero_ler(conexao, LEITOR_ID, duna, posicao=1)
    salvar_quero_ler(conexao, LEITOR_ID, fundacao)
    conexao.execute(
        text("UPDATE quero_ler SET criado_em = criado_em - interval '1 day' WHERE obra_id = :o"),
        {"o": duna},
    )

    lista = listar_quero_ler(conexao, LEITOR_ID)

    assert [(q.obra_id, q.titulo, q.posicao) for q in lista] == [
        (fundacao, "Fundação", None),
        (duna, "Duna", 1),
    ]
    assert lista[1].autores == ("Frank Herbert",)
    assert _eventos(conexao, "quero_ler_salvo") == [
        (duna, {"posicao": 1}),
        (fundacao, {"posicao": None}),
    ]


def test_salvar_de_novo_nao_duplica_nem_perde_a_posicao(conexao, duna) -> None:
    salvar_quero_ler(conexao, LEITOR_ID, duna, posicao=2)
    salvar_quero_ler(conexao, LEITOR_ID, duna)
    assert [q.posicao for q in listar_quero_ler(conexao, LEITOR_ID)] == [2]


def test_salvar_em_quero_ler_desfaz_a_dispensa(conexao, duna) -> None:
    dispensar(conexao, LEITOR_ID, duna)
    salvar_quero_ler(conexao, LEITOR_ID, duna)
    assert not dispensada(conexao, LEITOR_ID, duna)
    assert na_lista_quero_ler(conexao, LEITOR_ID, duna)


def test_obra_da_estante_nao_entra_em_quero_ler(conexao, duna) -> None:
    adicionar(conexao, LEITOR_ID, duna, 5, origem="busca")
    with pytest.raises(JaNaEstante):
        salvar_quero_ler(conexao, LEITOR_ID, duna)
    assert listar_quero_ler(conexao, LEITOR_ID) == []


def test_ja_li_tira_de_quero_ler(conexao, duna, fundacao) -> None:
    """Critério do R8: a Obra sai da lista quando o Leitor marca "Já li"."""
    salvar_quero_ler(conexao, LEITOR_ID, duna)
    salvar_quero_ler(conexao, LEITOR_ID, fundacao)

    adicionar(conexao, LEITOR_ID, duna, 4, origem="sugestao")

    assert [q.obra_id for q in listar_quero_ler(conexao, LEITOR_ID)] == [fundacao]


def test_tirar_de_quero_ler(conexao, duna) -> None:
    salvar_quero_ler(conexao, LEITOR_ID, duna)
    tirar_de_quero_ler(conexao, LEITOR_ID, duna)
    assert listar_quero_ler(conexao, LEITOR_ID) == []
