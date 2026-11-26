"""Importação do histórico do Goodreads (R9, SPEC §8.9, ADR 0011), contra o banco real.

O CSV de `tests/dados/goodreads/` segue o formato do export do Goodreads (cabeçalho atual,
ISBN como fórmula, série no título, nota 0 = sem Nota). As Obras do Catálogo são criadas
em cada teste; a Open Library só entra nos testes que passam um cliente com respostas
gravadas.
"""

from datetime import date
from pathlib import Path

import pytest
from fabricas import criar_obra
from http_gravado import TransporteGravado
from sqlalchemy import Connection, text

from recomendador import estante
from recomendador.catalogo.fontes.open_library import OpenLibrary
from recomendador.config import LEITOR_ID

ARQUIVO = Path(__file__).parent / "dados" / "goodreads" / "goodreads_library_export.csv"
CABECALHO_ANTIGO = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,Average Rating,"
    "Publisher,Binding,Number of Pages,Year Published,Original Publication Year,Date Read,"
    "Date Added,Bookshelves,Bookshelves with positions,Exclusive Shelf,My Review,Spoiler,"
    "Private Notes,Read Count,Recommended For,Recommended By,Owned Copies,"
    "Original Purchase Date,Original Purchase Location,Condition,Condition Description,BCID"
)


@pytest.fixture
def conteudo() -> bytes:
    return ARQUIVO.read_bytes()


@pytest.fixture
def catalogo(conexao: Connection) -> dict[str, int]:
    """As Obras do Catálogo que o arquivo de teste cita, menos as que devem falhar."""
    return {
        "hunger": criar_obra(
            conexao, "The Hunger Games", ("Suzanne Collins",), isbns=("9780439023481",)
        ),
        "blade": criar_obra(conexao, "The Blade Itself", ("Joe Abercrombie",)),
        "things": criar_obra(
            conexao, "Things Fall Apart", ("Chinua Achebe",), isbns=("9780385474542",)
        ),
        "gideon": criar_obra(
            conexao, "Gideon the Ninth", ("Tamsyn Muir",), isbns=("9781250313195",)
        ),
        "piranesi": criar_obra(conexao, "Piranesi", ("Susanna Clarke",)),
        "dune": criar_obra(conexao, "Dune", ("Frank Herbert",), isbns=("9780441013593",)),
        "sub": criar_obra(conexao, "Subcutanean", ("Aaron A. Reed",)),
        "wind": criar_obra(conexao, "The Name of the Wind", ("Patrick Rothfuss",)),
    }


def _por_titulo(linhas: list[estante.LinhaImportada]) -> dict[str, estante.LinhaImportada]:
    return {linha.titulo: linha for linha in linhas}


def _contar(conexao: Connection, sql: str, **params) -> int:
    return conexao.execute(text(sql), params).scalar_one()


# --- Leitura do arquivo ---


def test_le_o_csv_do_goodreads(conteudo: bytes) -> None:
    linhas = _por_titulo(estante.ler_goodreads(conteudo))

    hunger = linhas["The Hunger Games"]  # sem a série entre parênteses
    assert hunger.numero == 2  # a linha do arquivo, contando o cabeçalho
    assert hunger.autores == ("Suzanne Collins",)
    assert hunger.isbns == ("9780439023481",)  # o ISBN-10 é a mesma Edição
    assert (hunger.nota, hunger.estado, hunger.data) == (4, "lida", date(2024, 3, 10))

    things = linhas["Things Fall Apart"]
    assert things.isbns == ("9780385474542",)  # o ISBN-10 vira ISBN-13

    blade = linhas["The Blade Itself"]
    assert blade.isbns == ()  # `=""` é vazio

    gideon = linhas["Gideon the Ninth"]
    assert (gideon.nota, gideon.estado) == (None, "quero_ler")  # 0 é sem Nota
    assert gideon.data == date(2025, 11, 1)  # sem Date Read, vale Date Added
    assert linhas["Piranesi"].estado == "lendo"

    ulysses = linhas["Ulysses"]
    assert (ulysses.estado, ulysses.prateleira) == (None, "did-not-finish")

    assert linhas["Subcutanean"].autores == ("Aaron A. Reed", "Hanna Reed")
    assert len(estante.ler_goodreads(conteudo)) == 11


def test_aceita_bom_crlf_e_o_cabecalho_antigo() -> None:
    linha = (
        '1,Dune,Frank Herbert,"Herbert, Frank",,"=""""","=""9780441013593""",5,4.27,Ace,'
        "Paperback,688,2005,1965,2023/08/15,2023/08/01,,,read,,,,2,,,0,,,,,"
    )
    conteudo = ("﻿" + CABECALHO_ANTIGO + "\r\n" + linha + "\r\n").encode("utf-8")

    [dune] = estante.ler_goodreads(conteudo)

    assert (dune.titulo, dune.isbns, dune.nota) == ("Dune", ("9780441013593",), 5)


def test_recusa_arquivo_que_nao_e_do_goodreads() -> None:
    with pytest.raises(estante.ArquivoInvalido, match="Exclusive Shelf"):
        estante.ler_goodreads(b"Title,Author,My Rating\nDune,Frank Herbert,5\n")
    with pytest.raises(estante.ArquivoInvalido):
        estante.ler_goodreads(b"\xff\xfe\x00\x01 nao e texto")
    with pytest.raises(estante.ArquivoInvalido):
        estante.ler_goodreads(b"")


# --- Prévia ---


def test_previa_separa_encontradas_sem_correspondencia_e_ignoradas(
    conexao: Connection, conteudo: bytes, catalogo: dict[str, int]
) -> None:
    linhas = estante.ler_goodreads(conteudo)
    progresso: list[tuple[int, int]] = []

    previa = estante.preparar_importacao(
        conexao, LEITOR_ID, linhas, None, ao_avancar=lambda f, t: progresso.append((f, t))
    )

    assert [r.linha.titulo for r in previa.sem_correspondencia] == ["Um Livro Inexistente"]
    assert [linha.titulo for linha in previa.ignoradas] == ["Ulysses"]
    obras = {r.linha.numero: r.obra_id for r in previa.encontradas}
    assert len(obras) == 9
    assert set(obras.values()) == set(catalogo.values())
    assert progresso[-1] == (10, 10)  # a ignorada nem passa pela Resolução
    assert previa.taxa == pytest.approx(9 / 10)
    # A prévia não grava nada.
    assert _contar(conexao, "SELECT count(*) FROM leitura") == 0


def test_previa_usa_a_open_library_na_regra_2(conexao: Connection) -> None:
    dune = criar_obra(conexao, "Dune", ("Frank Herbert",), ol_work_key="/works/OL893414W")
    transporte = TransporteGravado()
    ol = OpenLibrary("teste", transporte=transporte, intervalo=0)
    duna_aleph = estante.LinhaImportada(
        numero=2,
        titulo="Duna",
        autores=("Frank Herbert",),
        isbns=("9788576573135",),
        nota=5,
        estado="lida",
        prateleira="read",
        data=None,
    )

    previa = estante.preparar_importacao(conexao, LEITOR_ID, [duna_aleph], ol)

    [r] = previa.encontradas
    assert (r.obra_id, r.resolucao.confianca) == (dune, "ol_work")
    assert "/isbn/9788576573135.json" in transporte.pedidos


# --- Importação ---


def test_importa_as_linhas_com_correspondencia(
    conexao: Connection, conteudo: bytes, catalogo: dict[str, int]
) -> None:
    """O critério do R9: ≥ 90 % das linhas com Obra no Catálogo entram sozinhas."""
    previa = estante.preparar_importacao(conexao, LEITOR_ID, estante.ler_goodreads(conteudo), None)

    relatorio = estante.importar(conexao, LEITOR_ID, previa)

    assert (relatorio.leituras, relatorio.quero_ler, relatorio.estou_lendo) == (6, 1, 1)
    assert relatorio.repetidas == 1  # as duas linhas de Dune
    assert (relatorio.sem_correspondencia, relatorio.ignoradas) == (1, 1)
    leituras = dict(
        conexao.execute(
            text("SELECT obra_id, nota FROM leitura WHERE leitor_id = :l"), {"l": LEITOR_ID}
        ).all()
    )
    com_obra_no_catalogo = 9 - relatorio.repetidas
    importadas = len(leituras) + relatorio.quero_ler + relatorio.estou_lendo
    assert importadas / com_obra_no_catalogo >= 0.9
    assert leituras[catalogo["hunger"]] == 4
    assert leituras[catalogo["sub"]] is None  # nota 0 no Goodreads
    assert leituras[catalogo["dune"]] == 5  # a lida mais recente, com Nota
    assert estante.na_lista_quero_ler(conexao, LEITOR_ID, catalogo["gideon"])
    assert estante.na_lista_estou_lendo(conexao, LEITOR_ID, catalogo["piranesi"])
    assert _contar(conexao, "SELECT count(*) FROM leitura WHERE origem <> 'importacao'") == 0


def test_eventos_ficam_fora_do_o3_e_o5(
    conexao: Connection, conteudo: bytes, catalogo: dict[str, int]
) -> None:
    previa = estante.preparar_importacao(conexao, LEITOR_ID, estante.ler_goodreads(conteudo), None)

    estante.importar(conexao, LEITOR_ID, previa)

    salvas = (
        conexao.execute(text("SELECT dados FROM evento WHERE tipo = 'leitura_salva'"))
        .scalars()
        .all()
    )
    assert len(salvas) == 6
    assert all(d["origem"] == "importacao" and d["duracao_s"] is None for d in salvas)
    assert _contar(conexao, "SELECT count(*) FROM evento WHERE tipo = 'ja_li_de_sugestao'") == 0
    [resumo] = (
        conexao.execute(text("SELECT dados FROM evento WHERE tipo = 'historico_importado'"))
        .scalars()
        .all()
    )
    assert resumo == {
        "fonte": "goodreads",
        "linhas": 11,
        "leituras": 6,
        "quero_ler": 1,
        "estou_lendo": 1,
        "ja_na_estante": 0,
        "repetidas": 1,
        "sem_correspondencia": 1,
        "ignoradas": 1,
    }


def test_estante_mostra_a_lida_mais_recente_primeiro(
    conexao: Connection, conteudo: bytes, catalogo: dict[str, int]
) -> None:
    previa = estante.preparar_importacao(conexao, LEITOR_ID, estante.ler_goodreads(conteudo), None)

    estante.importar(conexao, LEITOR_ID, previa)

    ordem = [i.obra_id for i in estante.listar(conexao, LEITOR_ID, ordem="data")]
    assert ordem == [
        catalogo["blade"],  # 2025/01/20
        catalogo["hunger"],  # 2024/03/10
        catalogo["dune"],  # 2023/08/15
        catalogo["wind"],  # 2021/09/09
        catalogo["sub"],  # 2020/03/06
        catalogo["things"],  # 2019/06/01
    ]


def test_vale_a_estante(conexao: Connection, conteudo: bytes, catalogo: dict[str, int]) -> None:
    estante.adicionar(conexao, LEITOR_ID, catalogo["hunger"], 2, origem="busca")
    estante.adicionar(conexao, LEITOR_ID, catalogo["things"], 3, origem="busca")
    estante.adicionar(conexao, LEITOR_ID, catalogo["gideon"], 5, origem="busca")
    previa = estante.preparar_importacao(conexao, LEITOR_ID, estante.ler_goodreads(conteudo), None)

    relatorio = estante.importar(conexao, LEITOR_ID, previa)

    assert estante.leitura_da_obra(conexao, LEITOR_ID, catalogo["hunger"]).nota == 2
    assert not estante.na_lista_quero_ler(conexao, LEITOR_ID, catalogo["gideon"])
    ja = {j.obra_id: (j.nota_estante, j.nota_arquivo) for j in relatorio.ja_na_estante}
    assert ja == {
        catalogo["hunger"]: (2, 4),
        catalogo["things"]: (3, 3),
        catalogo["gideon"]: (5, None),
    }
    assert relatorio.leituras == 4


def test_quero_ler_nao_tira_a_obra_de_estou_lendo(
    conexao: Connection, conteudo: bytes, catalogo: dict[str, int]
) -> None:
    estante.salvar_estou_lendo(conexao, LEITOR_ID, catalogo["gideon"])
    estante.salvar_quero_ler(conexao, LEITOR_ID, catalogo["blade"])
    previa = estante.preparar_importacao(conexao, LEITOR_ID, estante.ler_goodreads(conteudo), None)

    relatorio = estante.importar(conexao, LEITOR_ID, previa)

    assert estante.na_lista_estou_lendo(conexao, LEITOR_ID, catalogo["gideon"])
    assert not estante.na_lista_quero_ler(conexao, LEITOR_ID, catalogo["gideon"])
    assert relatorio.ja_na_lista == 1
    # A lida sai de Quero ler, como no "Já li".
    assert not estante.na_lista_quero_ler(conexao, LEITOR_ID, catalogo["blade"])
    assert estante.leitura_da_obra(conexao, LEITOR_ID, catalogo["blade"]).nota == 5


def test_reimportar_nao_duplica_e_resolve_pelo_isbn(
    conexao: Connection, conteudo: bytes, catalogo: dict[str, int]
) -> None:
    linhas = estante.ler_goodreads(conteudo)
    estante.importar(
        conexao, LEITOR_ID, estante.preparar_importacao(conexao, LEITOR_ID, linhas, None)
    )

    # O ISBN do arquivo de *The Name of the Wind* (achada pelo título) passou a ser da Obra.
    assert (
        _contar(
            conexao,
            "SELECT count(*) FROM obra_isbn WHERE isbn13 = '9780756404741' "
            "AND obra_id = :o AND origem = 'leitor'",
            o=catalogo["wind"],
        )
        == 1
    )
    previa = estante.preparar_importacao(conexao, LEITOR_ID, linhas, None)
    [wind] = [r for r in previa.encontradas if r.obra_id == catalogo["wind"]]
    assert wind.resolucao.confianca == "isbn"

    relatorio = estante.importar(conexao, LEITOR_ID, previa)

    assert (relatorio.leituras, relatorio.quero_ler, relatorio.estou_lendo) == (0, 0, 0)
    assert len(relatorio.ja_na_estante) == 6
    assert relatorio.ja_na_lista == 2
    assert _contar(conexao, "SELECT count(*) FROM leitura") == 6


# --- Revisão das linhas sem correspondência ---


def _linha_sem_correspondencia(
    conexao: Connection, conteudo: bytes, estado: str = "lida"
) -> estante.LinhaResolvida:
    linhas = [
        linha for linha in estante.ler_goodreads(conteudo) if linha.titulo == "Um Livro Inexistente"
    ]
    if estado != "lida":
        from dataclasses import replace

        linhas = [replace(linhas[0], estado=estado, nota=None)]
    [r] = estante.preparar_importacao(conexao, LEITOR_ID, linhas, None).sem_correspondencia
    return r


def test_revisao_escolhe_uma_candidata(conexao: Connection, conteudo: bytes) -> None:
    outra = criar_obra(conexao, "Outra Obra Qualquer", ("Fulano de Tal",))
    r = _linha_sem_correspondencia(conexao, conteudo)
    assert [c.obra_id for c in r.resolucao.candidatas] == [outra]

    desfecho = estante.importar_linha(conexao, LEITOR_ID, r, escolha=outra)

    assert (desfecho.obra_id, desfecho.destino) == (outra, "estante")
    leitura = estante.leitura_da_obra(conexao, LEITOR_ID, outra)
    assert (leitura.nota, leitura.origem) == (4, "importacao")


def test_revisao_cria_a_obra_nova(conexao: Connection, conteudo: bytes) -> None:
    r = _linha_sem_correspondencia(conexao, conteudo)

    desfecho = estante.importar_linha(conexao, LEITOR_ID, r)

    obra = conexao.execute(
        text("SELECT titulo, autores, origem FROM obra WHERE id = :o"), {"o": desfecho.obra_id}
    ).one()
    assert tuple(obra) == ("Um Livro Inexistente", ["Fulano de Tal"], "leitor")
    assert estante.leitura_da_obra(conexao, LEITOR_ID, desfecho.obra_id).nota == 4


def test_revisao_de_quero_ler_vai_para_a_lista(conexao: Connection, conteudo: bytes) -> None:
    r = _linha_sem_correspondencia(conexao, conteudo, estado="quero_ler")

    desfecho = estante.importar_linha(conexao, LEITOR_ID, r)

    assert desfecho.destino == "quero_ler"
    assert estante.na_lista_quero_ler(conexao, LEITOR_ID, desfecho.obra_id)


def test_revisao_respeita_a_estante(conexao: Connection, conteudo: bytes) -> None:
    outra = criar_obra(conexao, "Outra Obra Qualquer", ("Fulano de Tal",))
    estante.adicionar(conexao, LEITOR_ID, outra, 2, origem="busca")
    r = _linha_sem_correspondencia(conexao, conteudo)

    desfecho = estante.importar_linha(conexao, LEITOR_ID, r, escolha=outra)

    assert desfecho.destino == "ja_na_estante"
    assert estante.leitura_da_obra(conexao, LEITOR_ID, outra).nota == 2
