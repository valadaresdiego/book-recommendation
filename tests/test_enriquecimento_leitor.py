"""Passo 3 do `atualizar` (SPEC §10): Obras do Leitor enriquecidas pela API da Open Library."""

import httpx
from fabricas import criar_obra, linha
from http_gravado import TransporteGravado
from sqlalchemy import Connection, text

from recomendador.catalogo.fontes.open_library import OpenLibrary
from recomendador.pipeline.enriquecimento_leitor import enriquecer_obras_do_leitor

TORTO_ARADO_TODAVIA = "9786580309313"


def _ol(transporte: httpx.BaseTransport | None = None) -> OpenLibrary:
    return OpenLibrary("teste", transporte=transporte or TransporteGravado(), intervalo=0)


def _torto(conexao: Connection) -> int:
    return criar_obra(
        conexao,
        "Torto arado",
        ("Itamar Vieira Junior",),
        origem="leitor",
        isbns=(TORTO_ARADO_TODAVIA,),
    )


def test_enriquece_pelo_isbn(conexao: Connection) -> None:
    obra = _torto(conexao)

    resumo = enriquecer_obras_do_leitor(conexao, _ol())

    o = linha(conexao, "obra", obra)
    assert o["ol_work_key"] == "/works/OL24141556W"
    assert o["descricao"].startswith("Bibiana e Belonísia")
    assert o["enriquecida_em"] is not None
    assert o["titulo_exibicao"] == "Torto arado"  # não mexe no que o Leitor viu
    assuntos = conexao.execute(
        text("SELECT count(*) FROM obra_tag WHERE obra_id = :o AND contagem = 0"), {"o": obra}
    ).scalar_one()
    assert assuntos > 0
    assert (resumo.processadas, resumo.com_work) == (1, 1)


def test_obra_sem_isbn_e_marcada_sem_consultar(conexao: Connection) -> None:
    obra = criar_obra(conexao, "Caderno", ("Eu",), origem="leitor")
    transporte = TransporteGravado()

    enriquecer_obras_do_leitor(conexao, _ol(transporte))

    assert linha(conexao, "obra", obra)["enriquecida_em"] is not None
    assert transporte.pedidos == []


def test_so_obras_do_leitor_ainda_nao_enriquecidas(conexao: Connection) -> None:
    base = criar_obra(conexao, "Base", ("X",), isbns=(TORTO_ARADO_TODAVIA,))
    transporte = TransporteGravado()

    resumo = enriquecer_obras_do_leitor(conexao, _ol(transporte))

    assert resumo.processadas == 0
    assert linha(conexao, "obra", base)["enriquecida_em"] is None
    assert transporte.pedidos == []


def test_no_maximo_o_limite_por_execucao(conexao: Connection) -> None:
    for i in range(3):
        criar_obra(conexao, f"Sem ISBN {i}", ("Eu",), origem="leitor")
    assert enriquecer_obras_do_leitor(conexao, _ol(), limite=2).processadas == 2
    assert enriquecer_obras_do_leitor(conexao, _ol(), limite=2).processadas == 1


def test_open_library_fora_do_ar_deixa_pendente(conexao: Connection) -> None:
    obra = _torto(conexao)
    fora = _ol(TransporteGravado(erro=httpx.ConnectError("sem rede")))

    resumo = enriquecer_obras_do_leitor(conexao, fora)

    assert linha(conexao, "obra", obra)["enriquecida_em"] is None
    assert resumo.pendentes == 1


def test_work_ja_usada_por_outra_obra_nao_e_repetida(conexao: Connection) -> None:
    criar_obra(conexao, "Torto Arado", ("Itamar Vieira Junior",), ol_work_key="/works/OL24141556W")
    obra = _torto(conexao)

    enriquecer_obras_do_leitor(conexao, _ol())

    o = linha(conexao, "obra", obra)
    assert o["ol_work_key"] is None
    assert o["enriquecida_em"] is not None
