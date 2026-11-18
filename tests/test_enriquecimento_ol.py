"""`enriquecer-ol` sobre dumps sintéticos no formato da Open Library (SPEC §6.2)."""

import gzip
import json
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from recomendador.catalogo.isbn import completar_isbn13
from recomendador.pipeline.enriquecimento_ol import (
    DumpAusente,
    ObraDaBase,
    ResumoEnriquecimento,
    Work,
    conferir_works,
    enriquecer_ol,
    escolher_works,
)

DUNA_EN = completar_isbn13("978044117271")
DUNA_PT = completar_isbn13("978857657313")
FUNDACAO = completar_isbn13("978055338257")
FUNDACAO_10 = "0553382578"  # o mesmo ISBN, na forma de 10 dígitos
FUNDACAO_OUTRA = completar_isbn13("978055380371")
NEUROMANCER = completar_isbn13("978044156959")


def _dump(caminho: Path, tipo: str, registros: list[tuple[str, dict | str]]) -> None:
    with gzip.open(caminho, "wt", encoding="utf-8") as f:
        for chave, dados in registros:
            corpo = dados if isinstance(dados, str) else json.dumps(dados)
            f.write(f"/type/{tipo}\t{chave}\t1\t2026-10-01T00:00:00\t{corpo}\n")


def _work(titulo: str, *autores: str, subtitulo=None, descricao=None) -> dict:
    d: dict = {
        "title": titulo,
        "authors": [{"type": {"key": "/type/author_role"}, "author": {"key": a}} for a in autores],
    }
    if subtitulo:
        d["subtitle"] = subtitulo
    if descricao:
        d["description"] = descricao
    return d


def _edicao(work: str, isbn13=(), isbn10=(), idioma="eng", titulo="x", data=None) -> dict:
    d: dict = {"title": titulo, "works": [{"key": work}]}
    if idioma:
        d["languages"] = [{"key": f"/languages/{idioma}"}]
    if isbn13:
        d["isbn_13"] = list(isbn13)
    if isbn10:
        d["isbn_10"] = list(isbn10)
    if data:
        d["publish_date"] = data
    return d


@pytest.fixture
def dumps(tmp_path: Path) -> Path:
    _dump(
        tmp_path / "ol_dump_editions_2026-10-31.txt.gz",
        "edition",
        [
            ("/books/OL1M", _edicao("/works/OL1W", isbn13=[DUNA_EN])),
            ("/books/OL2M", _edicao("/works/OL1W", isbn13=["978-0-441-17271-9"])),
            ("/books/OL3M", _edicao("/works/OL9W", isbn13=[DUNA_EN])),  # voto minoritário
            (
                "/books/OL4M",
                _edicao("/works/OL1W", [DUNA_PT], idioma="por", titulo="Duna", data="2017"),
            ),
            (
                "/books/OL5M",
                _edicao("/works/OL1W", idioma="por", titulo="Duna (1985)", data="Maio de 1985"),
            ),
            ("/books/OL6M", _edicao("/works/OL3W", isbn10=[FUNDACAO_10])),
            ("/books/OL7M", _edicao("/works/OL3W", isbn13=[FUNDACAO])),
            # Neuromancer aponta para a mesma work com menos votos: fica sem work.
            ("/books/OL8M", _edicao("/works/OL3W", isbn13=[NEUROMANCER])),
            ("/books/OL9M", _edicao("/works/OL3W", isbn13=[FUNDACAO_OUTRA], idioma="spa")),
            ("/books/OL10M", '{"isbn_13": ["' + DUNA_EN + '"], quebrado'),
        ],
    )
    _dump(
        tmp_path / "ol_dump_works_2026-10-31.txt.gz",
        "work",
        [
            (
                "/works/OL1W",
                {
                    "title": "Dune",
                    "description": {"type": "/type/text", "value": "Em Arrakis..."},
                    "subjects": ["Science fiction", "Deserts", "science  fiction", ""],
                },
            ),
            ("/works/OL3W", {"title": "Foundation", "description": "Hari Seldon..."}),
            ("/works/OL9W", {"title": "Outra", "description": "não deve entrar"}),
        ],
    )
    return tmp_path


def _obra(
    conexao: Connection,
    titulo: str,
    isbn: str,
    tags: dict[str, int] | None = None,
    autor: str | None = None,
) -> int:
    obra_id = conexao.execute(
        text(
            "INSERT INTO obra (titulo, titulo_exibicao, autores, origem) "
            "VALUES (:t, :t, :a, 'base') RETURNING id"
        ),
        {"t": titulo, "a": [autor] if autor else []},
    ).scalar_one()
    conexao.execute(text("INSERT INTO obra_isbn VALUES (:i, :o)"), {"i": isbn, "o": obra_id})
    for tag, contagem in (tags or {}).items():
        conexao.execute(
            text("INSERT INTO obra_tag VALUES (:o, :t, :c)"),
            {"o": obra_id, "t": tag, "c": contagem},
        )
    return obra_id


def _linha(conexao: Connection, obra_id: int) -> dict:
    return dict(
        conexao.execute(text("SELECT * FROM obra WHERE id = :o"), {"o": obra_id}).mappings().one()
    )


def _consultar(conexao: Connection, sql: str, obra_id: int) -> dict | set:
    linhas = conexao.execute(text(sql), {"o": obra_id}).all()
    return dict(linhas) if linhas and len(linhas[0]) == 2 else {r[0] for r in linhas}


@pytest.fixture
def obras(conexao: Connection) -> dict[str, int]:
    return {
        "duna": _obra(conexao, "Dune", DUNA_EN, {"deserts": 10, "science-fiction": 50}),
        "fundacao": _obra(conexao, "Foundation", FUNDACAO),
        "neuromancer": _obra(conexao, "Neuromancer", NEUROMANCER),
    }


def test_enriquece_as_obras(conexao: Connection, dumps: Path, obras: dict[str, int]) -> None:
    resumo = enriquecer_ol(conexao, dumps)

    duna = _linha(conexao, obras["duna"])
    assert duna["ol_work_key"] == "/works/OL1W"
    assert duna["descricao"] == "Em Arrakis..."
    assert duna["titulo_exibicao"] == "Duna"  # a Edição em português mais recente
    assert duna["titulo"] == "Dune"
    assert duna["enriquecida_em"] is not None
    assert _consultar(
        conexao, "SELECT isbn13 FROM obra_isbn WHERE obra_id = :o", obras["duna"]
    ) == {
        DUNA_EN,
        DUNA_PT,
    }
    # Assuntos entram com contagem 0, sem sobrescrever a tag de leitores igual.
    assert _consultar(
        conexao, "SELECT tag, contagem FROM obra_tag WHERE obra_id = :o", obras["duna"]
    ) == {"deserts": 10, "science-fiction": 50, "science fiction": 0}

    fundacao = _linha(conexao, obras["fundacao"])
    assert fundacao["ol_work_key"] == "/works/OL3W"
    assert fundacao["descricao"] == "Hari Seldon..."
    assert fundacao["titulo_exibicao"] == "Foundation"  # sem Edição em português
    assert FUNDACAO_OUTRA in _consultar(
        conexao, "SELECT isbn13 FROM obra_isbn WHERE obra_id = :o", obras["fundacao"]
    )

    neuromancer = _linha(conexao, obras["neuromancer"])
    assert neuromancer["ol_work_key"] is None
    assert neuromancer["descricao"] is None
    assert neuromancer["enriquecida_em"] is not None

    assert resumo == ResumoEnriquecimento(
        obras=3, com_work=2, com_descricao=2, com_titulo_pt=1, isbns_novos=2
    )


def test_enriquecimento_e_idempotente(
    conexao: Connection, dumps: Path, obras: dict[str, int]
) -> None:
    primeira = enriquecer_ol(conexao, dumps)
    tags = conexao.execute(text("SELECT count(*) FROM obra_tag")).scalar_one()

    segunda = enriquecer_ol(conexao, dumps)

    assert segunda == ResumoEnriquecimento(**{**vars(primeira), "isbns_novos": 0})
    assert conexao.execute(text("SELECT count(*) FROM obra_tag")).scalar_one() == tags
    assert _linha(conexao, obras["duna"])["titulo_exibicao"] == "Duna"


def test_nao_sobrescreve_descricao_existente(
    conexao: Connection, dumps: Path, obras: dict[str, int]
) -> None:
    conexao.execute(text("UPDATE obra SET descricao = 'minha' WHERE id = :o"), {"o": obras["duna"]})
    enriquecer_ol(conexao, dumps)
    assert _linha(conexao, obras["duna"])["descricao"] == "minha"


def test_escolher_works() -> None:
    votos = Counter(
        {
            (1, "/works/A"): 3,
            (1, "/works/B"): 1,
            (2, "/works/A"): 2,
            (3, "/works/C"): 1,
            (3, "/works/D"): 1,
        }
    )
    assert escolher_works(votos) == {1: "/works/A", 3: "/works/C"}
    # Uma work que já pertence a uma Obra do Leitor não é usada.
    assert escolher_works(votos, {"/works/A"}) == {1: "/works/B", 3: "/works/C"}


def test_dump_ausente(conexao: Connection, tmp_path: Path) -> None:
    with pytest.raises(DumpAusente, match="ol_dump_editions"):
        enriquecer_ol(conexao, tmp_path)


def test_isbn_brasileiro_vale_como_edicao_em_portugues_sem_idioma(
    conexao: Connection, tmp_path: Path
) -> None:
    """Edição sem `languages` e com ISBN 978-85 ou 978-65 conta como Edição em português."""
    fundacao_br = completar_isbn13("978857657001")
    neuromancer_br = completar_isbn13("978655532001")
    _dump(
        tmp_path / "ol_dump_editions_2026-10-31.txt.gz",
        "edition",
        [
            ("/books/OL1M", _edicao("/works/OL3W", isbn13=[FUNDACAO])),
            (
                "/books/OL2M",
                _edicao("/works/OL3W", [fundacao_br], idioma=None, titulo="Fundação", data="2009"),
            ),
            ("/books/OL3M", _edicao("/works/OL5W", isbn13=[NEUROMANCER])),
            # Com idioma declarado, a Edição em português vence a inferida pelo ISBN,
            # mesmo sendo mais antiga.
            (
                "/books/OL4M",
                _edicao("/works/OL5W", idioma="por", titulo="Neuromancer", data="1991"),
            ),
            (
                "/books/OL5M",
                _edicao(
                    "/works/OL5W", [neuromancer_br], idioma=None, titulo="Neuromante", data="2016"
                ),
            ),
            # Sem idioma e com ISBN de fora do Brasil: não conta.
            (
                "/books/OL6M",
                _edicao("/works/OL3W", [FUNDACAO_OUTRA], idioma=None, titulo="Fundación"),
            ),
        ],
    )
    _dump(tmp_path / "ol_dump_works_2026-10-31.txt.gz", "work", [])
    fundacao = _obra(conexao, "Foundation", FUNDACAO)
    neuromancer = _obra(conexao, "Neuromancer", NEUROMANCER)

    resumo = enriquecer_ol(conexao, tmp_path)

    assert _linha(conexao, fundacao)["titulo_exibicao"] == "Fundação"
    assert _linha(conexao, neuromancer)["titulo_exibicao"] == "Neuromancer"
    assert resumo.com_titulo_pt == 2


HERBERT, CLAVELL, OUTRO = "/authors/OL1A", "/authors/OL9A", "/authors/OL7A"
DUNA_HODDER = completar_isbn13("978034083993")  # cai em Shōgun na Open Library
DUNA_ACE = completar_isbn13("978044101359")
MESSIAS = completar_isbn13("978044117269")
SHOGUN = completar_isbn13("978044017800")
XOGUM_BR = completar_isbn13("978853252001")


def test_work_de_outra_obra_e_trocada_pela_de_mesmo_titulo_e_autor(
    conexao: Connection, tmp_path: Path
) -> None:
    """O caso de *Dune*: o único ISBN da Base aponta para a work de *Shōgun*.

    A work certa é achada pelo título e pelas chaves de autor de outra Obra do mesmo autor
    (*Dune Messiah*); entre as works "Dune" de Herbert, vence a com mais Edições. *Shōgun*,
    cuja Obra estava numa work duplicada com menos Edições, fica com a work principal.
    """
    _dump(
        tmp_path / "ol_dump_editions_2026-10-31.txt.gz",
        "edition",
        [
            ("/books/OL1M", _edicao("/works/OL20W", isbn10=["0340839937"])),
            ("/books/OL2M", _edicao("/works/OL20W", [XOGUM_BR], idioma="por", titulo="Xógum")),
            ("/books/OL3M", _edicao("/works/OL20W")),
            ("/books/OL4M", _edicao("/works/OL21W", isbn13=[SHOGUN])),
            ("/books/OL5M", _edicao("/works/OL31W", isbn13=[MESSIAS])),
            ("/books/OL6M", _edicao("/works/OL10W", isbn13=[DUNA_ACE])),
            ("/books/OL7M", _edicao("/works/OL10W", [DUNA_PT], idioma="por", titulo="Duna")),
            ("/books/OL8M", _edicao("/works/OL10W")),
            ("/books/OL9M", _edicao("/works/OL11W")),  # duplicata pequena
            # Mais Edições, mas não são a Obra: outro título (subtítulo) ou outro autor.
            *[(f"/books/OL1{i}M", _edicao("/works/OL12W")) for i in range(5)],
            *[(f"/books/OL2{i}M", _edicao("/works/OL13W")) for i in range(5)],
        ],
    )
    _dump(
        tmp_path / "ol_dump_works_2026-10-31.txt.gz",
        "work",
        [
            ("/works/OL10W", _work("Dune", HERBERT, descricao="Em Arrakis...")),
            ("/works/OL11W", _work("Dune", HERBERT)),
            ("/works/OL12W", _work("Dune", HERBERT, OUTRO, subtitulo="House Harkonnen")),
            ("/works/OL13W", _work("Dune", OUTRO)),
            ("/works/OL20W", _work("Shōgun", CLAVELL, descricao="Blackthorne...")),
            ("/works/OL21W", _work("Shogun", CLAVELL)),
            ("/works/OL31W", _work("Dune Messiah", HERBERT)),
        ],
    )
    duna = _obra(conexao, "Dune", DUNA_HODDER, autor="Frank Herbert")
    _obra(conexao, "Dune Messiah", MESSIAS, autor="Frank Herbert")
    shogun = _obra(conexao, "Shōgun", SHOGUN, autor="James Clavell")
    # O que uma execução anterior deixou: a descrição de Shōgun em Dune.
    conexao.execute(
        text(
            "UPDATE obra SET ol_work_key = '/works/OL20W', descricao = 'Blackthorne...' "
            "WHERE id = :o"
        ),
        {"o": duna},
    )

    resumo = enriquecer_ol(conexao, tmp_path)

    linha = _linha(conexao, duna)
    assert linha["ol_work_key"] == "/works/OL10W"
    assert linha["descricao"] == "Em Arrakis..."
    assert linha["titulo_exibicao"] == "Duna"
    isbns = _consultar(conexao, "SELECT isbn13 FROM obra_isbn WHERE obra_id = :o", duna)
    assert {DUNA_ACE, DUNA_PT} <= isbns
    linha = _linha(conexao, shogun)
    assert linha["ol_work_key"] == "/works/OL20W"
    assert linha["titulo_exibicao"] == "Xógum"
    assert XOGUM_BR in _consultar(
        conexao, "SELECT isbn13 FROM obra_isbn WHERE obra_id = :o", shogun
    )
    assert (resumo.trocadas_por_errada, resumo.trocadas_por_irma) == (1, 1)
    assert (resumo.descartadas, resumo.achadas) == (0, 0)

    # Na execução seguinte os ISBNs novos já votam na work certa, e nada muda.
    segunda = enriquecer_ol(conexao, tmp_path)
    assert _linha(conexao, duna)["ol_work_key"] == "/works/OL10W"
    assert _linha(conexao, shogun)["ol_work_key"] == "/works/OL20W"
    assert segunda.com_work == resumo.com_work


def _obra_base(id: int, titulo: str, autor: str, original: str | None = None) -> ObraDaBase:
    return ObraDaBase.de(id, titulo, original, [autor])


def test_conferir_works() -> None:
    king, gibson, gibson_2, tolkien = "/authors/K", "/authors/G", "/authors/G2", "/authors/T"
    obras = [
        _obra_base(1, "Carrie", "Stephen King"),
        _obra_base(2, "It", "Stephen King"),
        _obra_base(3, "Burning Chrome", "William Gibson"),
        _obra_base(4, "Neuromancer", "William Gibson"),
        _obra_base(5, "The Hobbit", "J.R.R. Tolkien", "The Hobbit or There and Back Again"),
        _obra_base(6, "The Hobbit", "J.R.R. Tolkien"),  # a mesma Obra repetida na Base
        _obra_base(7, "Count Zero", "William Gibson"),
        _obra_base(8, "The Demon King", "Cinda Williams Chima"),
        _obra_base(9, "The Gray Wolf Throne", "Cinda Williams Chima"),
        _obra_base(10, "Kaleidoscope", "Danielle Steel"),
        _obra_base(11, "Zoya", "Danielle Steel"),
        _obra_base(12, "Crime and Punishment", "Fyodor Dostoyevsky"),
        _obra_base(13, "The Idiot", "Fyodor Dostoyevsky"),
    ]
    chima, steel, dost = "/authors/CH", "/authors/S", "/authors/D"
    works = {
        "carrie": Work.de(_work("Carrie", king)),
        "it": Work.de(_work("It", king)),
        "it-outro": Work.de(_work("It", "/authors/X")),
        "chrome": Work.de(_work("Burning Chrome", gibson)),
        "errada": Work.de(_work("Shōgun", "/authors/C")),
        "hobbit": Work.de(_work("The Hobbit", tolkien, subtitulo="or There and Back Again")),
        "hobbit-dup": Work.de(_work("The Hobbit", tolkien)),
        "zero": Work.de(_work("Count Zero", gibson_2)),  # outra chave de Gibson na OL
        "exiled": Work.de(_work("The Exiled Queen", chima)),
        "demon": Work.de(_work("The Demon King", chima)),
        "gray": Work.de(_work("The Gray Wolf Throne", chima)),
        "kaleid": Work.de(_work("Kaleidscope", steel)),
        "kaleido-dup": Work.de(_work("Kaleidoscope", steel)),
        "zoya": Work.de(_work("Zoya", steel)),
        "crime": Work.de(_work("Преступление и наказание", dost)),
        "crime-en": Work.de(_work("Crime and Punishment", dost)),
        "idiot": Work.de(_work("The Idiot", dost)),
    }
    votada = {
        **{1: "carrie", 3: "chrome", 4: "errada", 5: "hobbit-dup", 6: "hobbit", 7: "zero"},
        **{8: "exiled", 9: "gray", 10: "kaleid", 11: "zoya", 12: "crime", 13: "idiot"},
    }
    mesmo_titulo = {
        **{2: {"it", "it-outro"}, 5: {"hobbit", "hobbit-dup"}, 6: {"hobbit-dup"}},
        **{8: {"demon"}, 10: {"kaleido-dup"}, 12: {"crime-en"}},
    }
    edicoes = Counter(
        {"it": 5, "it-outro": 9, "hobbit": 50, "hobbit-dup": 2, "errada": 99}
        | {"exiled": 11, "demon": 8, "kaleid": 48, "kaleido-dup": 2, "crime": 1178, "crime-en": 18}
    )

    c = conferir_works(obras, votada, works, mesmo_titulo, edicoes)

    assert c.work_por_obra == {
        1: "carrie",
        2: "it",  # achada: título e chave de autor de King; a de outro autor não conta
        3: "chrome",
        # 4: a votada é de outro autor e outro título, e não há outra: sai.
        5: "hobbit-dup",  # a principal já é da Obra 6, que votou nela
        6: "hobbit",
        7: "zero",  # outra chave de autor, mas título igual: fica
        # Outro livro do mesmo autor: perde para a de título igual, mesmo tendo mais Edições.
        8: "demon",
        9: "gray",
        10: "kaleid",  # erro de digitação no título não faz parecer outra Obra
        11: "zoya",
        12: "crime",  # título em cirílico: não dá para comparar, fica a votada
        13: "idiot",
    }
    assert (c.trocadas_por_irma, c.trocadas_por_errada, c.descartadas, c.achadas) == (0, 1, 1, 1)
