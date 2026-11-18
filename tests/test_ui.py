"""Fluxos críticos da UI com `streamlit.testing.v1.AppTest` (SPEC §12).

As páginas abrem a transação com `estante.transacao()` e `catalogo.transacao()`; aqui as
duas devolvem a conexão do teste (dentro de um savepoint), e tudo é desfeito no fim.
"""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import streamlit as st
from fabricas import criar_genero, criar_obra, ligar_genero
from sqlalchemy import Connection
from streamlit.testing.v1 import AppTest

from recomendador import catalogo, estante
from recomendador.config import LEITOR_ID

APP = Path(__file__).parents[1] / "app"


@pytest.fixture(autouse=True)
def banco_de_teste(conexao: Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def transacao() -> Iterator[Connection]:
        with conexao.begin_nested():
            yield conexao

    monkeypatch.setattr(estante, "transacao", transacao)
    monkeypatch.setattr(catalogo, "transacao", transacao)
    monkeypatch.syspath_prepend(str(APP))  # as páginas importam `componentes`
    st.cache_data.clear()  # o cache de leitura sobrevive entre testes no mesmo processo
    yield
    st.cache_data.clear()
    sys.modules.pop("componentes", None)


def _pagina(nome: str) -> AppTest:
    """A página pelo `main.py`, para valerem o `st.navigation` e os links entre páginas."""
    at = AppTest.from_file(str(APP / "main.py"), default_timeout=10)
    at.switch_page(f"paginas/{nome}.py")
    return at


def test_estante_vazia_mostra_a_chamada() -> None:
    at = _pagina("estante").run()

    assert not at.exception
    assert "Sua Estante está vazia" in at.info[0].value


def test_estante_lista_as_leituras(conexao: Connection) -> None:
    obra = criar_obra(conexao, "Dune", ("Frank Herbert",), titulo_exibicao="Duna")
    estante.adicionar(conexao, LEITOR_ID, obra, 5, origem="busca")

    at = _pagina("estante").run()

    assert not at.exception
    assert any("**Duna**" in m.value for m in at.markdown)
    assert not at.info


def _com_notas(conexao: Connection, n: int) -> None:
    genero = criar_genero(conexao, "fantasia", "Fantasia")
    for i in range(8):
        obra = criar_obra(conexao, f"Obra {i}", (f"Autor {i}",), popularidade=100 - i)
        ligar_genero(conexao, obra, genero)
        if i < n:
            estante.adicionar(conexao, LEITOR_ID, obra, 4, origem="montagem")


def test_montagem_antes_de_5_notas(conexao: Connection) -> None:
    _com_notas(conexao, 4)
    at = _pagina("montagem")
    at.session_state["montagem-generos"] = ["fantasia"]
    at.run()

    assert not at.exception
    assert "4 de 5 Notas" in at.get("progress")[0].proto.text
    rotulos = [b.label for b in at.button]
    assert "Ver minhas sugestões" not in rotulos
    assert "Pular por enquanto" in rotulos
    # A grade traz as Obras do Gênero que ainda não estão na Estante.
    assert sum(r == "Não li" for r in rotulos) == 4


def test_montagem_com_5_notas_mostra_o_botao(conexao: Connection) -> None:
    _com_notas(conexao, 5)
    at = _pagina("montagem").run()

    assert not at.exception
    assert "5 de 5 Notas" in at.get("progress")[0].proto.text
    assert "Ver minhas sugestões" in [b.label for b in at.button]


def test_adicionar_avisa_que_ja_esta_na_estante(conexao: Connection) -> None:
    obra = criar_obra(conexao, "Dune", ("Frank Herbert",), titulo_exibicao="Duna")
    estante.adicionar(conexao, LEITOR_ID, obra, 5, origem="busca")
    at = _pagina("adicionar")
    at.session_state["adicionar-resolucao"] = catalogo.Resolucao("catalogo", None, obra_id=obra)
    at.run()

    assert not at.exception
    assert at.warning[0].value == "Você já tem Duna na Estante, com nota 5"
