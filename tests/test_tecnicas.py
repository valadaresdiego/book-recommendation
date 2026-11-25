"""`carregar-tecnicas` sobre dumps sintéticos da Open Library (SPEC §8.8, ADR 0009)."""

import gzip
import json
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from recomendador.catalogo.busca import buscar_no_catalogo
from recomendador.catalogo.generos import SLUG_BIOGRAFIAS, SLUG_TECNOLOGIA, sincronizar_generos
from recomendador.catalogo.isbn import completar_isbn13
from recomendador.config import LEITOR_ID
from recomendador.pipeline.tecnicas import CuradaInvalida, carregar_tecnicas
from tests.fabricas import criar_obra

ISBN_ALTA = completar_isbn13("978855081234")  # Edição brasileira da W2
ISBN_DUPLICADA = completar_isbn13("978013475759")  # da work duplicada de Refactoring
ISBN_LANCAMENTO = completar_isbn13("978180107000")

TECNICO = ["Computer programming"]


def _dump(caminho: Path, tipo: str, registros: list[tuple[str, dict]]) -> None:
    with gzip.open(caminho, "wt", encoding="utf-8") as f:
        for chave, dados in registros:
            f.write(f"/type/{tipo}\t{chave}\t1\t2026-10-01T00:00:00\t{json.dumps(dados)}\n")


def _work(chave: str, titulo: str, assuntos: list[str], autor="/authors/OL1A", **extra) -> dict:
    return {
        "key": chave,
        "title": titulo,
        "subjects": assuntos,
        "authors": [{"type": {"key": "/type/author_role"}, "author": {"key": autor}}],
        **extra,
    }


def _edicoes(work: str, n: int, editora="Springer", ano="2005", **extra) -> list[dict]:
    return [
        {"title": "x", "works": [{"key": work}], "publishers": [editora], "publish_date": ano}
        | extra
        for _ in range(n)
    ]


WORKS = [
    # Entram: ≥ 10 Edições; editora técnica com 2 Edições desde 2012; lançamento de 2024.
    _work("/works/OL1W", "Big Book", TECNICO, subtitle="Of Code"),
    _work("/works/OL2W", "Fluent Thing", ["Python (Computer program language)"], covers=[42]),
    _work("/works/OL3W", "Lancamento", ["Machine learning"], description="Novo."),
    # Saem: 1 Edição de 2014; editora técnica antes de 2012; editora acadêmica.
    _work("/works/OL4W", "Velho Packt", TECNICO),
    _work("/works/OL5W", "Antigo", TECNICO),
    _work("/works/OL6W", "Monografia", TECNICO),
    # Saem pelo ruído: ficção e anais; e uma work que não é técnica.
    _work("/works/OL7W", "Robos", ["Artificial intelligence", "Science fiction"]),
    _work("/works/OL8W", "Proceedings of Something", TECNICO),
    _work("/works/OL9W", "Romance", ["Love"]),
    # Lista curada: sem assunto técnico e com 1 Edição; a duplicada não vira Obra.
    _work("/works/OL10W", "Refactoring", ["Object oriented"], autor="/authors/OL2A"),
    _work("/works/OL11W", "Refactoring", TECNICO, autor="/authors/OL2A"),
    # Já são de Obras do Catálogo: Base e Leitor.
    _work("/works/OL12W", "Da Base", TECNICO),
    _work("/works/OL13W", "Do Leitor", TECNICO),
]

EDICOES = (
    _edicoes("/works/OL1W", 10)
    + _edicoes("/works/OL2W", 1, "O'Reilly Media", "2015")
    + _edicoes(
        "/works/OL2W",
        1,
        "Alta Books",
        "2019",
        title="Fluente",
        isbn_13=[ISBN_ALTA],
        languages=[{"key": "/languages/por"}],
    )
    + _edicoes("/works/OL3W", 1, "Packt Publishing", "March 2024", isbn_13=[ISBN_LANCAMENTO])
    + _edicoes("/works/OL4W", 1, "Packt Publishing", "2014")
    + _edicoes("/works/OL5W", 3, "Addison-Wesley", "2005")
    + _edicoes("/works/OL6W", 4, "Springer", "2020")
    + _edicoes("/works/OL7W", 20)
    + _edicoes("/works/OL8W", 12)
    + _edicoes("/works/OL9W", 20)
    + _edicoes("/works/OL10W", 1, "Addison-Wesley", "1999")
    + _edicoes("/works/OL11W", 12, isbn_13=[ISBN_DUPLICADA])
    + _edicoes("/works/OL12W", 15)
    + _edicoes("/works/OL13W", 15)
)

CURADOS = """
- work: /works/OL10W
  titulo: Refactoring
  autor: Martin Fowler
  fundir: [/works/OL11W]
"""


@pytest.fixture
def dumps(tmp_path: Path) -> Path:
    pasta = tmp_path / "ol"
    pasta.mkdir()
    _dump(pasta / "ol_dump_works_2026-10-31.txt.gz", "work", [(w["key"], w) for w in WORKS])
    _dump(
        pasta / "ol_dump_editions_2026-10-31.txt.gz",
        "edition",
        [(f"/books/OL{i}M", e) for i, e in enumerate(EDICOES, 1)],
    )
    _dump(
        pasta / "ol_dump_authors_2026-10-31.txt.gz",
        "author",
        [
            ("/authors/OL1A", {"key": "/authors/OL1A", "name": "Ana  Autora"}),
            ("/authors/OL2A", {"key": "/authors/OL2A", "name": "Martin Fowler"}),
        ],
    )
    return pasta


@pytest.fixture
def curados(tmp_path: Path) -> Path:
    caminho = tmp_path / "curados.yaml"
    caminho.write_text(CURADOS, encoding="utf-8")
    return caminho


@pytest.fixture
def catalogo(conexao: Connection) -> dict[str, int]:
    sincronizar_generos(conexao)
    return {
        "base": criar_obra(conexao, "Da Base", ol_work_key="/works/OL12W", popularidade=10),
        "leitor": criar_obra(conexao, "Do Leitor", ol_work_key="/works/OL13W", origem="leitor"),
    }


def _obras(conexao: Connection) -> dict[str, dict]:
    return {
        r["ol_work_key"]: dict(r)
        for r in conexao.execute(
            text("SELECT * FROM obra WHERE origem = 'open_library'")
        ).mappings()
    }


def _tecnicas(conexao: Connection) -> set[int]:
    return set(
        conexao.execute(
            text(
                "SELECT og.obra_id FROM obra_genero og JOIN genero g ON g.id = og.genero_id "
                "WHERE g.slug = :s AND og.forca = 1"
            ),
            {"s": SLUG_TECNOLOGIA},
        ).scalars()
    )


def test_corte_lista_curada_e_obras_que_ja_existem(
    conexao: Connection, dumps: Path, curados: Path, catalogo: dict[str, int]
) -> None:
    r = carregar_tecnicas(conexao, dumps, curados=curados)

    obras = _obras(conexao)
    assert set(obras) == {"/works/OL1W", "/works/OL2W", "/works/OL3W", "/works/OL10W"}
    assert r.por_ramo == {"edicoes": 1, "editora": 2, "curada": 1}
    assert (r.obras, r.novas, r.apagadas, r.do_leitor) == (4, 4, 0, 1)
    assert r.fundidas == 1  # a work duplicada de Refactoring

    big = obras["/works/OL1W"]
    assert big["titulo"] == big["titulo_exibicao"] == "Big Book: Of Code"
    assert big["autores"] == ["Ana Autora"]
    assert (big["edicoes_ol"], big["popularidade"], big["curada"]) == (10, 0, False)

    fluent = obras["/works/OL2W"]
    assert fluent["titulo_exibicao"] == "Fluente"  # a Edição em português
    assert fluent["tem_edicao_pt"] is True
    assert fluent["capa_url"] == "https://covers.openlibrary.org/b/id/42-M.jpg"

    lancamento = obras["/works/OL3W"]
    assert (lancamento["descricao"], lancamento["ano_original"]) == ("Novo.", 2024)

    refactoring = obras["/works/OL10W"]
    assert refactoring["curada"] is True
    assert refactoring["autores"] == ["Martin Fowler"]
    isbns = dict(
        conexao.execute(
            text("SELECT isbn13, obra_id FROM obra_isbn WHERE origem = 'open_library'")
        ).all()
    )
    assert isbns[ISBN_DUPLICADA] == refactoring["id"]  # a duplicada só empresta os ISBNs
    assert isbns[ISBN_LANCAMENTO] == lancamento["id"]

    # Tecnologia com força 1: as Obras da Open Library e a do Leitor; a da Base fica como está.
    assert _tecnicas(conexao) == {o["id"] for o in obras.values()} | {catalogo["leitor"]}
    assert catalogo["base"] not in _tecnicas(conexao)
    assuntos = conexao.execute(
        text("SELECT tag, contagem FROM obra_tag WHERE obra_id = :o"), {"o": fluent["id"]}
    ).all()
    assert assuntos == [("python (computer program language)", 0)]


def test_obra_do_leitor_e_tecnica_pelo_assunto_mesmo_fora_do_corte(
    conexao: Connection, dumps: Path, curados: Path, catalogo: dict[str, int]
) -> None:
    """§8.8, passo 6: o corte escolhe candidatas a Sugestão; a Obra que o Leitor já tem
    vira técnica pelo assunto. A work de ficção (ruído) continua de fora."""
    antigo = criar_obra(conexao, "Antigo", ol_work_key="/works/OL5W", origem="leitor")
    robos = criar_obra(conexao, "Robos", ol_work_key="/works/OL7W", origem="leitor")

    r = carregar_tecnicas(conexao, dumps, curados=curados)

    assert antigo in _tecnicas(conexao)
    assert robos not in _tecnicas(conexao)
    assert r.do_leitor == 2  # Antigo e Do Leitor
    assert "/works/OL5W" not in _obras(conexao)


def test_obra_do_leitor_de_biografias_nao_vira_tecnica(
    conexao: Connection, dumps: Path, curados: Path, catalogo: dict[str, int]
) -> None:
    """A mesma regra do `mapear-generos` (§6.3): Biografias e memórias sai de Tecnologia.
    Sem ela, a ordem dos comandos decidiria o Gênero da Obra."""
    conexao.execute(
        text(
            "INSERT INTO obra_genero (obra_id, genero_id, forca) "
            "SELECT :o, id, 0.4 FROM genero WHERE slug = :s"
        ),
        {"o": catalogo["leitor"], "s": SLUG_BIOGRAFIAS},
    )

    r = carregar_tecnicas(conexao, dumps, curados=curados)

    assert catalogo["leitor"] not in _tecnicas(conexao)
    assert r.do_leitor == 0


def test_carga_e_idempotente(
    conexao: Connection, dumps: Path, curados: Path, catalogo: dict[str, int]
) -> None:
    carregar_tecnicas(conexao, dumps, curados=curados)
    ids = {k: o["id"] for k, o in _obras(conexao).items()}

    r = carregar_tecnicas(conexao, dumps, curados=curados)

    assert {k: o["id"] for k, o in _obras(conexao).items()} == ids
    assert (r.novas, r.apagadas) == (0, 0)


def test_obra_fora_do_corte_sai_se_ninguem_usa(
    conexao: Connection, dumps: Path, curados: Path, catalogo: dict[str, int], tmp_path: Path
) -> None:
    carregar_tecnicas(conexao, dumps, curados=curados)
    fluent = _obras(conexao)["/works/OL2W"]["id"]
    conexao.execute(
        text("INSERT INTO quero_ler (leitor_id, obra_id) VALUES (:l, :o)"),
        {"l": LEITOR_ID, "o": fluent},
    )
    sem_editoras = tmp_path / "editoras.txt"
    sem_editoras.write_text("nenhuma editora assim\n", encoding="utf-8")

    r = carregar_tecnicas(conexao, dumps, curados=curados, editoras=sem_editoras)

    # Fluent Thing e Lançamento saem do corte: a primeira está em Quero ler e fica.
    assert set(_obras(conexao)) == {"/works/OL1W", "/works/OL2W", "/works/OL10W"}
    assert (r.apagadas, r.mantidas_em_uso) == (1, 1)
    assert fluent in _tecnicas(conexao)


def test_obra_mantida_fora_do_corte_continua_com_isbns_e_assuntos(
    conexao: Connection, dumps: Path, curados: Path, catalogo: dict[str, int], tmp_path: Path
) -> None:
    carregar_tecnicas(conexao, dumps, curados=curados)
    fluent = _obras(conexao)["/works/OL2W"]["id"]
    conexao.execute(
        text("INSERT INTO quero_ler (leitor_id, obra_id) VALUES (:l, :o)"),
        {"l": LEITOR_ID, "o": fluent},
    )
    sem_editoras = tmp_path / "editoras.txt"
    sem_editoras.write_text("nenhuma editora assim\n", encoding="utf-8")

    carregar_tecnicas(conexao, dumps, curados=curados, editoras=sem_editoras)

    # A Obra fica "sem os dados da carga anterior mudarem" (SPEC §8.8, passo 7).
    assert [o.obra_id for o in buscar_no_catalogo(conexao, ISBN_ALTA)] == [fluent]
    assuntos = conexao.execute(
        text("SELECT tag FROM obra_tag WHERE obra_id = :o"), {"o": fluent}
    ).scalars()
    assert list(assuntos) == ["python (computer program language)"]


@pytest.mark.parametrize(
    ("item", "mensagem"),
    [
        ("- {work: /works/OL99W, titulo: Sumida, autor: X}", "não está no dump"),
        ("- {work: /works/OL1W, titulo: Outro Livro, autor: X}", "não começa por"),
        (
            "- {work: /works/OL10W, titulo: Refactoring, autor: X, fundir: [/works/OL98W]}",
            "/works/OL98W.*não está no dump",
        ),
        (
            "- {work: /works/OL1W, titulo: Big, autor: X}\n"
            "- {work: /works/OL2W, titulo: Fluent, autor: X, fundir: [/works/OL1W]}",
            "repetidas",
        ),
    ],
)
def test_lista_curada_invalida(
    conexao: Connection, dumps: Path, tmp_path: Path, item: str, mensagem: str
) -> None:
    sincronizar_generos(conexao)
    caminho = tmp_path / "ruim.yaml"
    caminho.write_text(item, encoding="utf-8")
    with pytest.raises(CuradaInvalida, match=mensagem):
        carregar_tecnicas(conexao, dumps, curados=caminho)


def test_lista_curada_do_projeto_e_valida() -> None:
    from recomendador.pipeline.tecnicas import ler_curados

    curadas = ler_curados()
    assert len(curadas) >= 60
    assert all(c.work.startswith("/works/OL") and c.titulo and c.autor for c in curadas)
