"""Busca do R1: Catálogo local por trigram + Google Books, fundidos (SPEC §7.1)."""

import httpx
import pytest
from fabricas import criar_obra
from http_gravado import TransporteGravado
from sqlalchemy import Connection

from recomendador.catalogo import buscar
from recomendador.catalogo.fontes.google_books import GoogleBooks, montar_q

MESSIAS_ALEPH = "9788576572381"  # Messias de Duna (Aleph), presente na busca gravada


@pytest.fixture
def catalogo(conexao: Connection) -> dict[str, int]:
    return {
        "duna": criar_obra(
            conexao, "Dune", ("Frank Herbert",), popularidade=525_976, isbns=("9780340839935",)
        ),
        "messias": criar_obra(
            conexao,
            "Dune Messiah",
            ("Frank Herbert",),
            titulo_exibicao="Messias de Duna",
            popularidade=90_432,
            isbns=(MESSIAS_ALEPH,),
        ),
        "lincoln": criar_obra(conexao, "Lincoln", ("David Herbert Donald",), popularidade=9_000),
        "fundacao": criar_obra(
            conexao,
            "Foundation",
            ("Isaac Asimov",),
            titulo_exibicao="Fundação",
            popularidade=300_000,
            isbns=("9780553382570",),
        ),
    }


def _google(transporte: httpx.BaseTransport | None = None) -> GoogleBooks:
    return GoogleBooks("chave-falsa", transporte=transporte or TransporteGravado())


def test_q_do_google_books() -> None:
    assert montar_q("85-7657-313-X") == "isbn:857657313X"
    assert montar_q("978-85-7657-313-5") == "isbn:9788576573135"
    assert montar_q("  duna   herbert ") == "duna herbert"
    assert montar_q("1984") == "1984"  # 4 dígitos não é ISBN


def test_acha_por_titulo_e_autor_misturados(conexao: Connection, catalogo: dict) -> None:
    busca = buscar(conexao, "duna herbert", google=None)

    ids = [r.obra_id for r in busca.resultados]
    assert catalogo["duna"] in ids
    assert catalogo["messias"] in ids
    # "Herbert" sozinho não basta para passar à frente de quem também casa com "duna".
    if catalogo["lincoln"] in ids:
        assert ids.index(catalogo["lincoln"]) > ids.index(catalogo["duna"])


def test_ignora_acentos(conexao: Connection, catalogo: dict) -> None:
    busca = buscar(conexao, "fundacao asimov", google=None)
    assert busca.resultados[0].obra_id == catalogo["fundacao"]
    assert busca.resultados[0].titulo == "Fundação"


def test_acha_por_isbn_com_hifens(conexao: Connection, catalogo: dict) -> None:
    busca = buscar(conexao, "978-0-553-38257-0", google=None)
    assert [r.obra_id for r in busca.resultados] == [catalogo["fundacao"]]


def test_resultado_local_traz_capa_autor_e_ano(conexao: Connection) -> None:
    obra_id = criar_obra(
        conexao, "Neuromancer", ("William Gibson",), ano=1984, capa_url="https://capa/n.jpg"
    )
    [r] = buscar(conexao, "neuromancer", google=None).resultados
    assert (r.obra_id, r.titulo, r.autores, r.ano, r.capa_url) == (
        obra_id,
        "Neuromancer",
        ("William Gibson",),
        1984,
        "https://capa/n.jpg",
    )
    assert r.no_catalogo


def test_funde_edicao_do_google_cujo_isbn_esta_no_catalogo(
    conexao: Connection, catalogo: dict
) -> None:
    busca = buscar(conexao, "duna herbert", google=_google())

    messias = [r for r in busca.resultados if r.obra_id == catalogo["messias"]]
    assert len(messias) == 1  # sem duplicar
    assert messias[0].google_volume_id == "PM2uCgAAQBAJ"
    assert MESSIAS_ALEPH not in {i for r in busca.resultados if not r.no_catalogo for i in r.isbns}
    assert not busca.google_indisponivel


def test_catalogo_primeiro_depois_google(conexao: Connection, catalogo: dict) -> None:
    resultados = buscar(conexao, "duna herbert", google=_google()).resultados

    no_catalogo = [r.no_catalogo for r in resultados]
    assert no_catalogo == sorted(no_catalogo, reverse=True)
    assert any(not r.no_catalogo for r in resultados)
    assert all(r.titulo for r in resultados)


def test_google_fora_do_ar_mostra_so_o_catalogo(conexao: Connection, catalogo: dict) -> None:
    lento = TransporteGravado(erro=httpx.ReadTimeout("lento"))

    busca = buscar(conexao, "duna herbert", google=_google(lento))

    assert busca.google_indisponivel
    assert busca.resultados and all(r.no_catalogo for r in busca.resultados)


def test_busca_vazia(conexao: Connection, catalogo: dict) -> None:
    busca = buscar(conexao, "xyzzy qwerty", google=_google())
    assert busca.resultados == []
    assert not busca.google_indisponivel


def test_edicao_em_outro_idioma_nao_troca_o_item_do_catalogo(conexao: Connection) -> None:
    """*Hijos de Dune* (espanhol) tem ISBN de *Filhos de Duna*: o item segue em português."""
    filhos = criar_obra(
        conexao,
        "Children of Dune",
        ("Frank Herbert",),
        titulo_exibicao="Filhos de Duna",
        isbns=("9788497594325",),
    )

    resultados = buscar(conexao, "duna herbert", google=_google()).resultados

    dos_filhos = [r for r in resultados if r.obra_id == filhos]
    assert [r.titulo for r in dos_filhos] == ["Filhos de Duna"]
    assert all(r.titulo != "Hijos de Dune" for r in resultados)
