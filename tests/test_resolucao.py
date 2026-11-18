"""Resolução Edição → Obra (SPEC §7.2), com respostas gravadas da Open Library e do Google Books.

Um caso por regra, incluindo *Duna* (Aleph) → *Dune*. No banco real, a Obra *Dune* do
goodbooks ficou ligada a uma work duplicada da Open Library (`OL2918756W`), e não à
canônica (`OL893414W`); por isso a *Duna* da Aleph chega a *Dune* pela regra 3.
"""

import json

import httpx
import pytest
from fabricas import criar_obra, linha
from http_gravado import PASTA, TransporteGravado
from sqlalchemy import Connection, text

from recomendador.catalogo import (
    ResultadoBusca,
    informar_titulo_original,
    registrar_resolucao,
    resolver_manual,
    resolver_obra,
)
from recomendador.catalogo.fontes.google_books import _resultado
from recomendador.catalogo.fontes.open_library import OpenLibrary

DUNA_ALEPH = "9788576573135"
MESSIAS_ALEPH = "9788576572381"
TORTO_ARADO_TODAVIA = "9786580309313"


def _do_google(arquivo: str, volume_id: str) -> ResultadoBusca:
    itens = json.loads((PASTA / "gb" / arquivo).read_text(encoding="utf-8"))["items"]
    [r] = [_resultado(i) for i in itens if i["id"] == volume_id]
    assert r is not None
    return r


@pytest.fixture
def transporte() -> TransporteGravado:
    return TransporteGravado()


@pytest.fixture
def ol(transporte: TransporteGravado) -> OpenLibrary:
    return OpenLibrary("teste", transporte=transporte, intervalo=0)


@pytest.fixture
def duna_aleph() -> ResultadoBusca:
    return _do_google("isbn_9788576573135.json", "co7YzgEACAAJ")


def _dune(conexao: Connection, work: str = "/works/OL2918756W") -> int:
    return criar_obra(
        conexao,
        "Dune",
        ("Frank Herbert",),
        ol_work_key=work,
        popularidade=525_976,
        isbns=("9780340839935",),
    )


def _messias(conexao: Connection, isbns: tuple[str, ...] = ()) -> int:
    return criar_obra(conexao, "Dune Messiah", ("Frank Herbert",), popularidade=90_432, isbns=isbns)


def test_regra_1_isbn_no_catalogo(
    conexao: Connection, ol: OpenLibrary, transporte: TransporteGravado
) -> None:
    messias = _messias(conexao, isbns=(MESSIAS_ALEPH,))
    escolhido = _do_google("duna_herbert.json", "PM2uCgAAQBAJ")

    r = resolver_obra(conexao, escolhido, ol)

    assert (r.obra_id, r.confianca) == (messias, "isbn")
    assert transporte.pedidos == []  # nem chega a consultar a Open Library


def test_regra_2_work_da_open_library(
    conexao: Connection, ol: OpenLibrary, duna_aleph: ResultadoBusca
) -> None:
    dune = _dune(conexao, work="/works/OL893414W")

    r = resolver_obra(conexao, duna_aleph, ol)

    assert (r.obra_id, r.confianca) == (dune, "ol_work")


def test_regra_3_duna_aleph_vira_dune_pelo_titulo_original(
    conexao: Connection, ol: OpenLibrary, duna_aleph: ResultadoBusca
) -> None:
    dune = _dune(conexao)  # work duplicada, como no banco real
    _messias(conexao)  # "Dune" está contido em "Dune Messiah": não pode ganhar

    r = resolver_obra(conexao, duna_aleph, ol)

    assert (r.obra_id, r.confianca) == (dune, "titulo_original")


def test_regra_3_exige_o_mesmo_sobrenome(
    conexao: Connection, ol: OpenLibrary, duna_aleph: ResultadoBusca
) -> None:
    criar_obra(conexao, "Dune", ("Kara Kennedy",), ol_work_key="/works/OL1W")

    r = resolver_obra(conexao, duna_aleph, ol)

    assert r.confianca == "nova"


def test_regra_4_obra_nova_com_dados_da_open_library(conexao: Connection, ol: OpenLibrary) -> None:
    criar_obra(conexao, "Vidas Secas", ("Graciliano Ramos",))
    salvar = criar_obra(conexao, "Salvar o Fogo", ("Itamar Vieira Junior",))
    escolhido = ResultadoBusca(
        titulo="Torto arado",
        autores=("Itamar Vieira Junior",),
        ano=2019,
        capa_url=None,
        google_volume_id="vol-torto",
        isbns=(TORTO_ARADO_TODAVIA,),
        idioma="pt",
    )

    r = resolver_obra(conexao, escolhido, ol)

    assert r.confianca == "nova" and r.obra_id is None
    nova = r.obra_nova
    assert nova is not None
    assert nova.titulo == "Torto Arado"  # o título da work
    assert nova.ol_work_key == "/works/OL24141556W"
    assert nova.descricao and nova.descricao.startswith("Bibiana e Belonísia")
    assert nova.autores == ("Itamar Vieira Junior",)
    assert nova.capa_url == "https://covers.openlibrary.org/b/id/12369648-M.jpg"
    assert nova.enriquecida
    assert len(r.candidatas) <= 5
    assert [c.obra_id for c in r.candidatas] == [salvar]  # mesmo autor; Vidas Secas não


def test_regra_4_sem_a_open_library_usa_o_google_books(
    conexao: Connection, ol: OpenLibrary
) -> None:
    escolhido = _do_google("torto_arado.json", "lL2GDwAAQBAJ")  # OL devolve 404

    r = resolver_obra(conexao, escolhido, ol)

    assert r.confianca == "nova"
    assert r.obra_nova is not None
    assert r.obra_nova.titulo == escolhido.titulo
    assert r.obra_nova.ol_work_key is None
    assert not r.obra_nova.enriquecida


def test_open_library_fora_do_ar_nao_impede_a_resolucao(
    conexao: Connection, duna_aleph: ResultadoBusca
) -> None:
    fora = OpenLibrary(
        "teste", transporte=TransporteGravado(erro=httpx.ConnectError("sem rede")), intervalo=0
    )
    _dune(conexao)

    r = resolver_obra(conexao, duna_aleph, fora)

    assert r.confianca == "nova"
    assert r.obra_nova is not None and not r.obra_nova.enriquecida


def test_item_do_catalogo_nao_precisa_de_resolucao(
    conexao: Connection, ol: OpenLibrary, transporte: TransporteGravado
) -> None:
    dune = _dune(conexao)
    item = ResultadoBusca(
        titulo="Dune", autores=("Frank Herbert",), ano=1965, capa_url=None, obra_id=dune
    )

    r = resolver_obra(conexao, item, ol)

    assert (r.obra_id, r.confianca) == (dune, "catalogo")
    assert transporte.pedidos == []


# --- registrar_resolucao: grava a Edição e, se for o caso, a Obra nova ---


def test_registrar_grava_a_edicao_e_os_isbns_dela(
    conexao: Connection, ol: OpenLibrary, duna_aleph: ResultadoBusca
) -> None:
    dune = _dune(conexao)
    r = resolver_obra(conexao, duna_aleph, ol)

    registrada = registrar_resolucao(conexao, r)

    assert registrada.obra_id == dune
    edicao = linha(conexao, "edicao", registrada.edicao_id)
    assert edicao["obra_id"] == dune
    assert edicao["google_volume_id"] == "co7YzgEACAAJ"
    assert edicao["isbn13"] == DUNA_ALEPH
    assert edicao["titulo"] == "Duna"
    assert edicao["idioma"] == "pt"
    assert edicao["ol_edition_key"] == "/books/OL28969075M"
    # O ISBN da Edição passa a resolver pela regra 1 da próxima vez.
    assert (
        conexao.execute(
            text("SELECT obra_id FROM obra_isbn WHERE isbn13 = :i"), {"i": DUNA_ALEPH}
        ).scalar_one()
        == dune
    )


def test_edicao_em_portugues_vira_o_titulo_de_exibicao_se_nao_houver(
    conexao: Connection, ol: OpenLibrary, duna_aleph: ResultadoBusca
) -> None:
    dune = _dune(conexao)
    registrar_resolucao(conexao, resolver_obra(conexao, duna_aleph, ol))
    assert linha(conexao, "obra", dune)["titulo_exibicao"] == "Duna"


def test_nao_troca_titulo_de_exibicao_que_ja_esta_em_portugues(
    conexao: Connection, ol: OpenLibrary
) -> None:
    messias = criar_obra(
        conexao,
        "Dune Messiah",
        ("Frank Herbert",),
        titulo_exibicao="O Messias de Duna",
        isbns=(MESSIAS_ALEPH,),
    )
    escolhido = _do_google("duna_herbert.json", "PM2uCgAAQBAJ")
    registrar_resolucao(conexao, resolver_obra(conexao, escolhido, ol))
    assert linha(conexao, "obra", messias)["titulo_exibicao"] == "O Messias de Duna"


def test_registrar_obra_nova(conexao: Connection, ol: OpenLibrary) -> None:
    escolhido = ResultadoBusca(
        titulo="Torto arado",
        autores=("Itamar Vieira Junior",),
        ano=2019,
        capa_url="https://books.google/torto.jpg",
        google_volume_id="vol-torto",
        isbns=(TORTO_ARADO_TODAVIA,),
        idioma="pt",
    )
    r = resolver_obra(conexao, escolhido, ol)

    registrada = registrar_resolucao(conexao, r)

    obra = linha(conexao, "obra", registrada.obra_id)
    assert obra["origem"] == "leitor"
    assert obra["titulo"] == "Torto Arado"
    assert obra["titulo_exibicao"] == "Torto arado"  # o da Edição em português escolhida
    assert obra["ol_work_key"] == "/works/OL24141556W"
    assert obra["enriquecida_em"] is not None
    assert obra["autores"] == ["Itamar Vieira Junior"]
    tags = conexao.execute(
        text("SELECT tag, contagem FROM obra_tag WHERE obra_id = :o"), {"o": obra["id"]}
    ).all()
    assert tags and all(c == 0 for _, c in tags)  # assuntos da OL, como no §6.2


def test_escolher_uma_candidata_usa_a_obra_do_catalogo(
    conexao: Connection, ol: OpenLibrary
) -> None:
    escolhido = _do_google("torto_arado.json", "lL2GDwAAQBAJ")
    # Cadastrada sem autor: a regra 3 não casa, mas o título a põe entre as candidatas.
    existente = criar_obra(conexao, "Torto Arado")
    r = resolver_obra(conexao, escolhido, ol)
    assert existente in {c.obra_id for c in r.candidatas}
    obras_antes = conexao.execute(text("SELECT count(*) FROM obra")).scalar_one()

    registrada = registrar_resolucao(conexao, r, escolha=existente)

    assert registrada.obra_id == existente
    assert linha(conexao, "edicao", registrada.edicao_id)["obra_id"] == existente
    assert conexao.execute(text("SELECT count(*) FROM obra")).scalar_one() == obras_antes


def test_escolha_fora_das_candidatas_e_recusada(conexao: Connection, ol: OpenLibrary) -> None:
    escolhido = _do_google("torto_arado.json", "lL2GDwAAQBAJ")
    r = resolver_obra(conexao, escolhido, ol)
    with pytest.raises(ValueError, match="candidata"):
        registrar_resolucao(conexao, r, escolha=-1)


# --- Cadastro manual: regras 3 e 4 com o texto digitado ---


def test_manual_acha_pelo_titulo_original(conexao: Connection) -> None:
    dune = _dune(conexao)
    r = resolver_manual(conexao, "Dune", "Frank Herbert")
    assert (r.obra_id, r.confianca) == (dune, "titulo_original")


def test_manual_sem_correspondencia_propoe_obra_nova_e_candidatas(conexao: Connection) -> None:
    dune = _dune(conexao)

    r = resolver_manual(conexao, "Duna", "Frank Herbert")

    assert r.confianca == "nova"
    assert r.obra_nova is not None
    assert (r.obra_nova.titulo, r.obra_nova.autores) == ("Duna", ("Frank Herbert",))
    assert r.edicao is None
    assert dune in {c.obra_id for c in r.candidatas}

    registrada = registrar_resolucao(conexao, r)
    assert registrada.edicao_id is None
    assert linha(conexao, "obra", registrada.obra_id)["origem"] == "leitor"


# --- Título original informado à mão (R1) ---


def test_titulo_original_a_mao_acha_a_obra_do_catalogo(
    conexao: Connection, ol: OpenLibrary, duna_aleph: ResultadoBusca
) -> None:
    dune = _dune(conexao)
    sem_ol = resolver_obra(conexao, duna_aleph, None)  # sem a OL, cai na regra 4
    assert sem_ol.confianca == "nova"

    r = informar_titulo_original(conexao, sem_ol, "Dune")

    assert (r.obra_id, r.confianca, r.edicao) == (dune, "titulo_original", duna_aleph)


def test_titulo_original_a_mao_sem_correspondencia_fica_na_obra_nova(
    conexao: Connection, ol: OpenLibrary
) -> None:
    escolhido = _do_google("torto_arado.json", "lL2GDwAAQBAJ")
    r = informar_titulo_original(conexao, resolver_obra(conexao, escolhido, ol), "Torto Arado")

    assert r.confianca == "nova"
    assert r.obra_nova is not None and r.obra_nova.titulo_original == "Torto Arado"
    registrada = registrar_resolucao(conexao, r)
    assert linha(conexao, "obra", registrada.obra_id)["titulo_original"] == "Torto Arado"
