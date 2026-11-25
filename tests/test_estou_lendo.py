"""Estou lendo (R13), da fase 5 (SPEC §8.7, ADR 0008), contra o banco real."""

import pytest
from fabricas import criar_edicao, criar_obra
from sqlalchemy import Connection, text

from recomendador.config import LEITOR_ID
from recomendador.estante import (
    JaNaEstante,
    adicionar,
    dispensada,
    dispensar,
    listar_estou_lendo,
    listar_quero_ler,
    na_lista_estou_lendo,
    na_lista_quero_ler,
    salvar_estou_lendo,
    salvar_quero_ler,
    tirar_de_estou_lendo,
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


def test_salvar_em_estou_lendo_lista_da_mais_recente(conexao, duna, fundacao) -> None:
    salvar_estou_lendo(conexao, LEITOR_ID, duna, posicao=2)
    salvar_estou_lendo(conexao, LEITOR_ID, fundacao)
    conexao.execute(
        text("UPDATE estou_lendo SET criado_em = criado_em - interval '1 day' WHERE obra_id = :o"),
        {"o": duna},
    )

    lista = listar_estou_lendo(conexao, LEITOR_ID)

    assert [(i.obra_id, i.titulo, i.posicao) for i in lista] == [
        (fundacao, "Fundação", None),
        (duna, "Duna", 2),
    ]
    assert lista[1].autores == ("Frank Herbert",)
    assert _eventos(conexao, "leitura_iniciada") == [
        (duna, {"posicao": 2}),
        (fundacao, {"posicao": None}),
    ]


def test_salvar_de_novo_nao_duplica_nem_perde_a_posicao(conexao, duna) -> None:
    salvar_estou_lendo(conexao, LEITOR_ID, duna, posicao=4)
    salvar_estou_lendo(conexao, LEITOR_ID, duna)
    assert [i.posicao for i in listar_estou_lendo(conexao, LEITOR_ID)] == [4]


def test_de_quero_ler_para_estou_lendo_leva_a_posicao(conexao, duna) -> None:
    """O5: a posição em "Para você" salva em Quero ler vai junto para Estou lendo."""
    salvar_quero_ler(conexao, LEITOR_ID, duna, posicao=3)

    salvar_estou_lendo(conexao, LEITOR_ID, duna)

    assert not na_lista_quero_ler(conexao, LEITOR_ID, duna)
    assert [i.posicao for i in listar_estou_lendo(conexao, LEITOR_ID)] == [3]
    assert _eventos(conexao, "leitura_iniciada") == [(duna, {"posicao": 3})]


def test_salvar_em_estou_lendo_desfaz_a_dispensa(conexao, duna) -> None:
    dispensar(conexao, LEITOR_ID, duna)
    salvar_estou_lendo(conexao, LEITOR_ID, duna)
    assert not dispensada(conexao, LEITOR_ID, duna)
    assert na_lista_estou_lendo(conexao, LEITOR_ID, duna)


def test_dispensar_tira_de_estou_lendo(conexao, duna) -> None:
    salvar_estou_lendo(conexao, LEITOR_ID, duna)
    dispensar(conexao, LEITOR_ID, duna)
    assert not na_lista_estou_lendo(conexao, LEITOR_ID, duna)


def test_voltar_para_quero_ler_tira_de_estou_lendo_e_leva_a_posicao(conexao, duna) -> None:
    salvar_estou_lendo(conexao, LEITOR_ID, duna, posicao=5)

    salvar_quero_ler(conexao, LEITOR_ID, duna)

    assert not na_lista_estou_lendo(conexao, LEITOR_ID, duna)
    assert [q.posicao for q in listar_quero_ler(conexao, LEITOR_ID)] == [5]


def test_obra_da_estante_nao_entra_em_estou_lendo(conexao, duna) -> None:
    """Sem releitura na v1 (ADR 0008)."""
    adicionar(conexao, LEITOR_ID, duna, 5, origem="busca")
    with pytest.raises(JaNaEstante):
        salvar_estou_lendo(conexao, LEITOR_ID, duna)
    assert listar_estou_lendo(conexao, LEITOR_ID) == []


def test_ja_li_tira_de_estou_lendo(conexao, duna, fundacao) -> None:
    """Critério do R13: a Obra sai da lista quando o Leitor marca "Já li"."""
    salvar_estou_lendo(conexao, LEITOR_ID, duna)
    salvar_estou_lendo(conexao, LEITOR_ID, fundacao)

    adicionar(conexao, LEITOR_ID, duna, 4, origem="sugestao")

    assert [i.obra_id for i in listar_estou_lendo(conexao, LEITOR_ID)] == [fundacao]


def test_parei_de_ler(conexao, duna) -> None:
    salvar_estou_lendo(conexao, LEITOR_ID, duna)
    tirar_de_estou_lendo(conexao, LEITOR_ID, duna)
    assert listar_estou_lendo(conexao, LEITOR_ID) == []
    assert not na_lista_quero_ler(conexao, LEITOR_ID, duna)


def test_a_edicao_vai_de_quero_ler_a_estou_lendo_e_a_leitura(conexao, duna) -> None:
    """A Edição escolhida na busca acompanha a Obra até a Leitura (ADR 0010)."""
    edicao = criar_edicao(conexao, duna, "Duna", capa_url="https://capa/duna-aleph.jpg")
    salvar_quero_ler(conexao, LEITOR_ID, duna, edicao_id=edicao)

    salvar_estou_lendo(conexao, LEITOR_ID, duna)
    [item] = listar_estou_lendo(conexao, LEITOR_ID)
    assert item.capa_url == "https://capa/duna-aleph.jpg"

    assert adicionar(conexao, LEITOR_ID, duna, 4, origem="catalogo").edicao_id == edicao


def test_voltar_para_quero_ler_leva_a_edicao(conexao, duna) -> None:
    edicao = criar_edicao(conexao, duna, "Duna")
    salvar_quero_ler(conexao, LEITOR_ID, duna, edicao_id=edicao)
    salvar_estou_lendo(conexao, LEITOR_ID, duna)

    salvar_quero_ler(conexao, LEITOR_ID, duna)

    assert adicionar(conexao, LEITOR_ID, duna, 4, origem="catalogo").edicao_id == edicao
