"""Dispensa (R7) e Quero ler (R8), da fase 4 (SPEC §8.6), contra o banco real."""

import pytest
from fabricas import criar_edicao, criar_genero, criar_obra, ligar_genero
from sqlalchemy import Connection, text

from recomendador.config import LEITOR_ID
from recomendador.estante import (
    JaEmQueroLer,
    JaNaEstante,
    adicionar,
    desfazer_dispensa,
    dispensada,
    dispensar,
    listar_quero_ler,
    na_lista_quero_ler,
    quero_ler_da_obra,
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
    assert _eventos(conexao, "sugestao_dispensada")[0] == (duna, {"posicao": 3, "lista": None})


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
        (duna, {"posicao": 1, "lista": None}),
        (fundacao, {"posicao": None, "lista": None}),
    ]


def test_salvar_de_novo_avisa_e_nao_grava_nada(conexao, duna) -> None:
    """Obra já na lista: avisa, sem outro `quero_ler_salvo` e sem perder a posição."""
    salvar_quero_ler(conexao, LEITOR_ID, duna, posicao=2)
    antes = _eventos(conexao, "quero_ler_salvo")

    with pytest.raises(JaEmQueroLer, match="Duna já está na sua lista Quero ler"):
        salvar_quero_ler(conexao, LEITOR_ID, duna)

    assert [q.posicao for q in listar_quero_ler(conexao, LEITOR_ID)] == [2]
    assert _eventos(conexao, "quero_ler_salvo") == antes


def test_quero_ler_da_obra(conexao, duna, fundacao) -> None:
    salvar_quero_ler(conexao, LEITOR_ID, duna, posicao=2)

    assert quero_ler_da_obra(conexao, LEITOR_ID, duna).titulo == "Duna"
    assert quero_ler_da_obra(conexao, LEITOR_ID, fundacao) is None


def test_livro_buscado_entra_sem_posicao_e_fica_fora_do_o2(conexao, duna) -> None:
    """Vindo da busca, o `quero_ler_salvo` não tem posição: a consulta do O2 só conta
    eventos com `posicao <= 10` (`reports/consultas-metricas.sql`)."""
    salvar_quero_ler(conexao, LEITOR_ID, duna)

    assert _eventos(conexao, "quero_ler_salvo") == [(duna, {"posicao": None, "lista": None})]
    no_o2 = conexao.execute(
        text(
            "SELECT count(*) FROM evento WHERE tipo = 'quero_ler_salvo' "
            "AND (dados->>'posicao')::int <= 10"
        )
    ).scalar_one()
    assert no_o2 == 0


def test_a_edicao_da_busca_fica_na_lista_e_mostra_a_capa(conexao, duna) -> None:
    edicao = criar_edicao(conexao, duna, "Duna", capa_url="https://capa/duna-aleph.jpg")

    salvar_quero_ler(conexao, LEITOR_ID, duna, edicao_id=edicao)

    [item] = listar_quero_ler(conexao, LEITOR_ID)
    assert item.capa_url == "https://capa/duna-aleph.jpg"


def test_ja_li_leva_a_edicao_de_quero_ler_para_a_leitura(conexao, duna) -> None:
    edicao = criar_edicao(conexao, duna, "Duna")
    salvar_quero_ler(conexao, LEITOR_ID, duna, edicao_id=edicao)

    leitura = adicionar(conexao, LEITOR_ID, duna, 5, origem="catalogo")

    assert leitura.edicao_id == edicao


def test_a_edicao_do_ja_li_vale_mais_que_a_da_lista(conexao, duna) -> None:
    da_lista = criar_edicao(conexao, duna, "Duna")
    outra = criar_edicao(conexao, duna, "Dune")
    salvar_quero_ler(conexao, LEITOR_ID, duna, edicao_id=da_lista)

    leitura = adicionar(conexao, LEITOR_ID, duna, 5, origem="busca", edicao_id=outra)

    assert leitura.edicao_id == outra


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


def test_quero_ler_marca_as_obras_tecnicas(conexao, duna) -> None:
    """Uma Obra do Gênero "Tecnologia" vai para a aba própria de Quero ler."""
    tecnologia = criar_genero(conexao, "tecnologia", "Tecnologia")
    ficcao = criar_genero(conexao, "ficcao-cientifica", "Ficção científica")
    ligar_genero(conexao, duna, ficcao)
    ddd = criar_obra(conexao, "Domain-Driven Design", ("Eric Evans",), origem="open_library")
    ligar_genero(conexao, ddd, tecnologia)
    salvar_quero_ler(conexao, LEITOR_ID, duna)
    salvar_quero_ler(conexao, LEITOR_ID, ddd)

    assert {q.obra_id: q.tecnica for q in listar_quero_ler(conexao, LEITOR_ID)} == {
        duna: False,
        ddd: True,
    }
    assert quero_ler_da_obra(conexao, LEITOR_ID, ddd).tecnica


def test_a_lista_de_para_voce_vai_nos_eventos_do_o2(conexao, duna, fundacao) -> None:
    """O O2 separa a lista geral da aba "Tecnologia" (SPEC §7.6, §8.8)."""
    dispensar(conexao, LEITOR_ID, duna, posicao=2, lista="tecnologia")
    salvar_quero_ler(conexao, LEITOR_ID, fundacao, posicao=1, lista="geral")

    assert _eventos(conexao, "sugestao_dispensada") == [
        (duna, {"posicao": 2, "lista": "tecnologia"})
    ]
    assert _eventos(conexao, "quero_ler_salvo") == [(fundacao, {"posicao": 1, "lista": "geral"})]
