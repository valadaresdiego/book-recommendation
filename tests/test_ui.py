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
from sqlalchemy import Connection, text
from streamlit.testing.v1 import AppTest

from recomendador import catalogo, estante, recomendacao
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
    monkeypatch.setattr(recomendacao, "transacao", transacao)
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


def _catalogo_com_vizinhos(conexao: Connection) -> list[int]:
    """6 Obras; na execução de conteúdo ativa, cada uma tem as outras 5 como Vizinhos."""
    obras = [
        criar_obra(conexao, f"Obra {i}", (f"Autor {i}",), titulo_exibicao=f"Livro {i}")
        for i in range(6)
    ]
    execucao = conexao.execute(
        text(
            "INSERT INTO execucao_modelo (tipo, modelo, ativa) "
            "VALUES ('conteudo', 'teste', true) RETURNING id"
        )
    ).scalar_one()
    conexao.execute(
        text("INSERT INTO vizinho VALUES (:e, :o, :v, :s, :p)"),
        [
            {"e": execucao, "o": o, "v": v, "s": 0.9 - 0.1 * pos, "p": pos}
            for o in obras
            for pos, v in enumerate((v for v in obras if v != o), 1)
        ],
    )
    return obras


def test_para_voce_com_poucas_notas_pede_mais(conexao: Connection) -> None:
    obras = _catalogo_com_vizinhos(conexao)
    estante.adicionar(conexao, LEITOR_ID, obras[0], 5, origem="busca")

    at = _pagina("para_voce").run()

    assert not at.exception
    assert "Avalie pelo menos 3 livros" in at.info[0].value
    assert "1 de 3" in at.get("progress")[0].proto.text


def test_para_voce_mostra_o_motivo_e_registra_a_exibicao(conexao: Connection) -> None:
    obras = _catalogo_com_vizinhos(conexao)
    for o, nota in zip(obras[:3], (5, 4, 5), strict=True):
        estante.adicionar(conexao, LEITOR_ID, o, nota, origem="busca")

    at = _pagina("para_voce").run()

    assert not at.exception
    assert [b.label for b in at.button if b.label.startswith("**Livro")] == [
        "**Livro 3**",
        "**Livro 4**",
        "**Livro 5**",
    ]
    assert any(m.value.startswith("Porque você deu 5 a *Livro") for m in at.markdown)
    exibidas = conexao.execute(
        text("SELECT count(*) FROM evento WHERE tipo = 'sugestao_exibida'")
    ).scalar_one()
    assert exibidas == 3


def test_pagina_da_obra(conexao: Connection) -> None:
    obras = _catalogo_com_vizinhos(conexao)
    estante.adicionar(conexao, LEITOR_ID, obras[1], 4, origem="busca")
    at = _pagina("obra")
    at.query_params["obra"] = str(obras[0])
    at.run()

    assert not at.exception
    assert at.title[0].value == "Livro 0"
    rotulos = [b.label for b in at.button]
    assert [r for r in rotulos if r.startswith("Livro")] == [f"Livro {i}" for i in range(1, 6)]
    assert any("✅ lido" in c.value for c in at.caption)
    assert "Ainda não há dados de outros leitores para este livro" in [c.value for c in at.caption]


# --- fase 4: Quero ler, Dispensa, filtros e Motivo detalhado (SPEC §8.6) ---


def _para_voce_com_3_notas(conexao: Connection) -> list[int]:
    obras = _catalogo_com_vizinhos(conexao)
    for o, nota in zip(obras[:3], (5, 4, 5), strict=True):
        estante.adicionar(conexao, LEITOR_ID, o, nota, origem="busca")
    return obras


def _titulos_em_para_voce(at: AppTest) -> list[str]:
    return [b.label for b in at.button if b.label.startswith("**Livro")]


def test_quero_ler_tira_de_para_voce_e_entra_na_lista(conexao: Connection) -> None:
    obras = _para_voce_com_3_notas(conexao)
    at = _pagina("para_voce").run()
    assert _titulos_em_para_voce(at) == ["**Livro 3**", "**Livro 4**", "**Livro 5**"]

    at.button(key=f"pv-{obras[3]}-quero").click().run()

    assert not at.exception
    assert _titulos_em_para_voce(at) == ["**Livro 4**", "**Livro 5**"]
    posicao = conexao.execute(
        text("SELECT posicao FROM quero_ler WHERE obra_id = :o"), {"o": obras[3]}
    ).scalar_one()
    assert posicao == 1

    lista = _pagina("quero_ler").run()
    assert not lista.exception
    assert "**Livro 3**" in [b.label for b in lista.button]
    assert "Tirar da lista" in [b.label for b in lista.button]


def test_quero_ler_vazia_mostra_a_chamada() -> None:
    at = _pagina("quero_ler").run()

    assert not at.exception
    assert "Sua lista Quero ler está vazia" in at.info[0].value


def test_nao_tenho_interesse_dispensa_a_sugestao(conexao: Connection) -> None:
    obras = _para_voce_com_3_notas(conexao)
    at = _pagina("para_voce").run()

    at.button(key=f"pv-{obras[4]}-dispensar").click().run()

    assert not at.exception
    assert _titulos_em_para_voce(at) == ["**Livro 3**", "**Livro 5**"]
    dados = conexao.execute(
        text("SELECT dados FROM evento WHERE tipo = 'sugestao_dispensada'")
    ).scalar_one()
    assert dados == {"posicao": 2, "lista": "geral"}


def test_filtro_de_genero_e_motivo_detalhado(conexao: Connection) -> None:
    obras = _para_voce_com_3_notas(conexao)
    fantasia = criar_genero(conexao, "fantasia", "Fantasia")
    ligar_genero(conexao, obras[4], fantasia)
    at = _pagina("para_voce")
    at.session_state["pv-generos"] = ["fantasia"]
    at.run()

    assert not at.exception
    assert _titulos_em_para_voce(at) == ["**Livro 4**"]
    detalhe = [m.value for m in at.markdown if ", sua nota " in m.value]
    assert len(detalhe) == 3
    assert detalhe[0].startswith("*Livro 0*, sua nota 5: ")
    assert all(d.endswith(" %") for d in detalhe)


def test_pagina_da_obra_dispensada_oferece_desfazer(conexao: Connection) -> None:
    obras = _catalogo_com_vizinhos(conexao)
    estante.dispensar(conexao, LEITOR_ID, obras[2])
    at = _pagina("obra")
    at.query_params["obra"] = str(obras[2])
    at.run()

    assert not at.exception
    assert at.warning[0].value == "Você dispensou este livro de Para você."

    at.button(key=f"obra-{obras[2]}-desfazer").click().run()

    assert not at.exception
    assert not at.warning
    assert not estante.dispensada(conexao, LEITOR_ID, obras[2])


# --- fase 5: Estou lendo (SPEC §8.7) ---


def test_comecei_a_ler_tira_de_para_voce_e_entra_em_estou_lendo(conexao: Connection) -> None:
    obras = _para_voce_com_3_notas(conexao)
    at = _pagina("para_voce").run()

    at.button(key=f"pv-{obras[3]}-lendo").click().run()

    assert not at.exception
    assert _titulos_em_para_voce(at) == ["**Livro 4**", "**Livro 5**"]
    posicao = conexao.execute(
        text("SELECT posicao FROM estou_lendo WHERE obra_id = :o"), {"o": obras[3]}
    ).scalar_one()
    assert posicao == 1

    lista = _pagina("estou_lendo").run()
    assert not lista.exception
    assert "**Livro 3**" in [b.label for b in lista.button]

    lista.button(key=f"el-{obras[3]}-parei").click().run()

    assert not lista.exception
    assert not estante.na_lista_estou_lendo(conexao, LEITOR_ID, obras[3])
    assert "Você não está lendo nada agora" in lista.info[0].value


def test_de_quero_ler_a_ja_li_passando_por_estou_lendo(conexao: Connection) -> None:
    """O5: a Obra salva de "Para você" chega à Estante com `origem='sugestao'`."""
    obras = _para_voce_com_3_notas(conexao)
    estante.salvar_quero_ler(conexao, LEITOR_ID, obras[4], posicao=2)
    quero = _pagina("quero_ler").run()

    quero.button(key=f"ql-{obras[4]}-lendo").click().run()

    assert not quero.exception
    assert not estante.na_lista_quero_ler(conexao, LEITOR_ID, obras[4])

    lendo = _pagina("estou_lendo").run()
    lendo.button(key=f"el-{obras[4]}-salvar").click().run()

    assert not lendo.exception
    assert not estante.na_lista_estou_lendo(conexao, LEITOR_ID, obras[4])
    assert estante.leitura_da_obra(conexao, LEITOR_ID, obras[4]).origem == "sugestao"
    dados = conexao.execute(
        text("SELECT dados FROM evento WHERE tipo = 'ja_li_de_sugestao'")
    ).scalar_one()
    assert dados == {"posicao": 2, "nota": None}


def test_estou_lendo_vazia_mostra_a_chamada() -> None:
    at = _pagina("estou_lendo").run()

    assert not at.exception
    assert "Você não está lendo nada agora" in at.info[0].value


def test_pagina_da_obra_em_estou_lendo(conexao: Connection) -> None:
    obras = _catalogo_com_vizinhos(conexao)
    at = _pagina("obra")
    at.query_params["obra"] = str(obras[2])
    at.run()

    at.button(key=f"obra-{obras[2]}-lendo").click().run()

    assert not at.exception
    assert at.info[0].value == "Você está lendo este livro."
    rotulos = [b.label for b in at.button]
    assert "Parei de ler" in rotulos
    assert "Quero ler" not in rotulos
    assert "Não tenho interesse" not in rotulos


# --- fase 6: aba "Tecnologia" (SPEC §8.8) ---


def test_lista_geral_nao_tem_o_chip_tecnologia(conexao: Connection) -> None:
    """Os livros técnicos têm a aba própria; na lista geral o chip só traria os da Base."""
    _para_voce_com_3_notas(conexao)
    criar_genero(conexao, "fantasia", "Fantasia")
    criar_genero(conexao, "tecnologia", "Tecnologia")

    at = _pagina("para_voce").run()

    assert not at.exception
    opcoes = list(at.pills(key="pv-generos").options)
    assert "Fantasia" in opcoes
    assert "Tecnologia" not in opcoes


def test_aba_tecnologia_mostra_as_sugestoes_tecnicas(conexao: Connection) -> None:
    obras = _para_voce_com_3_notas(conexao)
    tecnicas = [
        criar_obra(conexao, f"Tec {i}", (f"Dev {i}",), origem="open_library") for i in range(2)
    ]
    execucao = conexao.execute(
        text(
            "INSERT INTO execucao_modelo (tipo, modelo, ativa) "
            "VALUES ('tecnico', 'teste', true) RETURNING id"
        )
    ).scalar_one()
    conexao.execute(
        text("INSERT INTO vizinho VALUES (:e, :o, :v, :s, :p)"),
        [
            {"e": execucao, "o": o, "v": v, "s": 0.8 - 0.1 * p, "p": p}
            for o in obras[:3]
            for p, v in enumerate(tecnicas, 1)
        ],
    )
    at = _pagina("para_voce").run()
    assert _titulos_em_para_voce(at) == ["**Livro 3**", "**Livro 4**", "**Livro 5**"]
    assert [p.key for p in at.pills] == ["pv-generos"]

    at.segmented_control(key="pv-lista").set_value("tecnologia").run()

    assert not at.exception
    assert not at.pills  # a aba técnica não tem os chips de Gênero
    assert [b.label for b in at.button if b.label.startswith("**Tec")] == ["**Tec 0**", "**Tec 1**"]
    at.button(key=f"pv-{tecnicas[1]}-dispensar").click().run()
    exibidas = conexao.execute(
        text(
            "SELECT dados ->> 'lista', count(*) FROM evento "
            "WHERE tipo = 'sugestao_exibida' GROUP BY 1 ORDER BY 1"
        )
    ).all()
    assert exibidas == [("geral", 3), ("tecnologia", 2)]
    dispensa = conexao.execute(
        text("SELECT dados FROM evento WHERE tipo = 'sugestao_dispensada'")
    ).scalar_one()
    assert dispensa == {"posicao": 2, "lista": "tecnologia"}


# --- Busca → Quero ler (R8, SPEC §7.1 e §8.6) ---


def _duna_da_busca() -> catalogo.ResultadoBusca:
    return catalogo.ResultadoBusca(
        titulo="Duna",
        autores=("Frank Herbert",),
        ano=2017,
        capa_url="https://capa/duna-aleph.jpg",
        google_volume_id="vol-duna",
        isbns=("9788576573135",),
        editora="Aleph",
        idioma="pt",
    )


def test_busca_guarda_obra_do_catalogo_em_quero_ler(conexao: Connection) -> None:
    obra = criar_obra(conexao, "Dune", ("Frank Herbert",))
    at = _pagina("adicionar")
    at.session_state["adicionar-resolucao"] = catalogo.Resolucao(
        "isbn", _duna_da_busca(), obra_id=obra
    )
    at.run()
    assert "Salvar na Estante" in [b.label for b in at.button]

    at.button(key="adicionar-quero").click().run()

    assert not at.exception
    assert at.success[0].value == "Duna entrou na sua lista Quero ler."
    assert estante.leitura_da_obra(conexao, LEITOR_ID, obra) is None
    [item] = estante.listar_quero_ler(conexao, LEITOR_ID)
    assert (item.obra_id, item.capa_url, item.posicao) == (
        obra,
        "https://capa/duna-aleph.jpg",
        None,
    )
    dados = conexao.execute(
        text("SELECT dados FROM evento WHERE tipo = 'quero_ler_salvo'")
    ).scalar_one()
    assert dados == {"posicao": None, "lista": None}  # fora do O2


def test_busca_guarda_obra_nova_em_quero_ler_e_o_ja_li_leva_a_edicao(
    conexao: Connection,
) -> None:
    nova = catalogo.ObraProposta(
        titulo="Duna",
        titulo_original=None,
        titulo_exibicao="Duna",
        autores=("Frank Herbert",),
        ano_original=1965,
        descricao=None,
        capa_url=None,
        ol_work_key=None,
    )
    at = _pagina("quero_ler")
    at.session_state["quero_ler-resolucao"] = catalogo.Resolucao(
        "nova", _duna_da_busca(), obra_nova=nova
    )
    at.run()
    assert "Salvar na Estante" not in [b.label for b in at.button]
    assert not at.get("feedback")  # sem estrelas: a Nota fica para o "Já li"

    at.button(key="quero_ler-quero").click().run()

    assert not at.exception
    # A lista deixou de estar vazia: a busca fica aberta para mostrar a mensagem.
    assert at.success[0].value == "Duna entrou na sua lista Quero ler."
    [item] = estante.listar_quero_ler(conexao, LEITOR_ID)
    assert item.titulo == "Duna"
    origem = conexao.execute(
        text("SELECT origem FROM obra WHERE id = :o"), {"o": item.obra_id}
    ).scalar_one()
    assert origem == "leitor"

    lista = _pagina("quero_ler").run()
    lista.button(key=f"ql-{item.obra_id}-salvar").click().run()

    leitura = estante.leitura_da_obra(conexao, LEITOR_ID, item.obra_id)
    assert leitura.origem == "catalogo"
    edicao = conexao.execute(
        text("SELECT edicao_id FROM leitura WHERE obra_id = :o"), {"o": item.obra_id}
    ).scalar_one()
    assert edicao is not None


def test_busca_em_quero_ler_avisa_obra_ja_na_estante(conexao: Connection) -> None:
    obra = criar_obra(conexao, "Dune", ("Frank Herbert",), titulo_exibicao="Duna")
    estante.adicionar(conexao, LEITOR_ID, obra, 5, origem="busca")
    at = _pagina("quero_ler")
    at.session_state["quero_ler-resolucao"] = catalogo.Resolucao("catalogo", None, obra_id=obra)
    at.run()

    assert not at.exception
    assert at.warning[0].value == "Você já tem Duna na Estante, com nota 5"
    assert "Quero ler" not in [b.label for b in at.button]
    assert estante.listar_quero_ler(conexao, LEITOR_ID) == []


def test_busca_avisa_obra_ja_em_quero_ler(conexao: Connection) -> None:
    obra = criar_obra(conexao, "Dune", ("Frank Herbert",), titulo_exibicao="Duna")
    estante.salvar_quero_ler(conexao, LEITOR_ID, obra)
    at = _pagina("adicionar")
    at.session_state["adicionar-resolucao"] = catalogo.Resolucao("catalogo", None, obra_id=obra)
    at.run()

    assert not at.exception
    assert at.info[0].value == "Duna já está na sua lista Quero ler."
    rotulos = [b.label for b in at.button]
    assert "Salvar na Estante" in rotulos  # dá para marcar como lida
    assert "Quero ler" not in rotulos


def test_quero_ler_vazia_abre_a_busca() -> None:
    at = _pagina("quero_ler").run()

    assert not at.exception
    assert at.text_input[0].label == "Título, autor ou ISBN"
    assert not at.toggle


def test_quero_ler_com_itens_esconde_a_busca(conexao: Connection) -> None:
    obra = criar_obra(conexao, "Dune", ("Frank Herbert",), titulo_exibicao="Duna")
    estante.salvar_quero_ler(conexao, LEITOR_ID, obra)
    at = _pagina("quero_ler").run()

    assert not at.text_input
    at.toggle(key="ql-buscar").set_value(True).run()

    assert not at.exception
    assert at.text_input[0].label == "Título, autor ou ISBN"


def test_candidata_ja_em_quero_ler_avisa_com_o_titulo_dela(conexao: Connection) -> None:
    """`registrar_resolucao` troca o título da Obra dentro da transação (Edição em
    português, §7.2); o aviso, depois de desfeita, mostra o título que ficou."""
    obra = criar_obra(conexao, "Torto Arado", ("Itamar Vieira Junior",), origem="leitor")
    estante.salvar_quero_ler(conexao, LEITOR_ID, obra)
    quadrinhos = catalogo.ResultadoBusca(
        titulo="Torto arado: Romance em quadrinhos",
        autores=("Rafael Calça", "Itamar Vieira Junior"),
        ano=2026,
        capa_url=None,
        google_volume_id="vol-quadrinhos",
        idioma="pt",
    )
    nova = catalogo.ObraProposta(
        titulo=quadrinhos.titulo,
        titulo_original=None,
        titulo_exibicao=quadrinhos.titulo,
        autores=quadrinhos.autores,
        ano_original=2026,
        descricao=None,
        capa_url=None,
        ol_work_key=None,
    )
    candidata = catalogo.Candidata(obra, "Torto Arado", ("Itamar Vieira Junior",), None, None)
    at = _pagina("adicionar")
    at.session_state["adicionar-resolucao"] = catalogo.Resolucao(
        "nova", quadrinhos, obra_nova=nova, candidatas=(candidata,)
    )
    at.run()
    at.radio(key="adicionar-candidata").set_value(obra).run()

    at.button(key="adicionar-quero").click().run()

    assert not at.exception
    assert at.warning[0].value == "Torto Arado já está na sua lista Quero ler"
    edicoes = conexao.execute(text("SELECT count(*) FROM edicao")).scalar_one()
    assert edicoes == 0
