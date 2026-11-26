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
from recomendador.pipeline.tecnicas import CuradaInvalida, carregar_tecnicas, ler_criterio
from tests.fabricas import criar_obra

ISBN_ALTA = completar_isbn13("978855081234")  # Edição brasileira da W2
ISBN_DUPLICADA = completar_isbn13("978013475759")  # da work duplicada de Refactoring
ISBN_LANCAMENTO = completar_isbn13("978180107000")

TECNICO = ["Computer programming"]


def _dump(caminho: Path, tipo: str, registros: list[tuple[str, dict]]) -> None:
    with gzip.open(caminho, "wt", encoding="utf-8") as f:
        for chave, dados in registros:
            f.write(f"/type/{tipo}\t{chave}\t1\t2026-10-01T00:00:00\t{json.dumps(dados)}\n")


def _work(
    chave: str, titulo: str, assuntos: list[str], autor: str | tuple = "/authors/OL1A", **extra
) -> dict:
    autores = (autor,) if isinstance(autor, str) else autor
    return {
        "key": chave,
        "title": titulo,
        "subjects": assuntos,
        "authors": [{"type": {"key": "/type/author_role"}, "author": {"key": a}} for a in autores],
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
    # Autor repetido na work: a mesma chave duas vezes e outra chave com a inicial do meio.
    _work(
        "/works/OL1W",
        "Big Book",
        TECNICO,
        autor=("/authors/OL1A", "/authors/OL3A", "/authors/OL1A"),
        subtitle="Of Code",
    ),
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
        subtitle="programando  com estilo",
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
            ("/authors/OL3A", {"key": "/authors/OL3A", "name": "Ana B. Autora"}),
        ],
    )
    return pasta


@pytest.fixture
def curados(tmp_path: Path) -> Path:
    caminho = tmp_path / "curados.yaml"
    caminho.write_text(CURADOS, encoding="utf-8")
    return caminho


@pytest.fixture
def separadas(tmp_path: Path) -> Path:
    """Vazia: a lista do projeto tem works que não estão nos dumps sintéticos."""
    caminho = tmp_path / "separadas.yaml"
    caminho.write_text("", encoding="utf-8")
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
    conexao: Connection, dumps: Path, curados: Path, separadas: Path, catalogo: dict[str, int]
) -> None:
    r = carregar_tecnicas(conexao, dumps, curados=curados, separadas=separadas)

    obras = _obras(conexao)
    assert set(obras) == {"/works/OL1W", "/works/OL2W", "/works/OL3W", "/works/OL10W"}
    assert r.por_ramo == {"edicoes": 1, "editora": 2, "curada": 1}
    assert (r.obras, r.novas, r.apagadas, r.do_leitor) == (4, 4, 0, 1)
    assert r.fundidas == 1  # a work duplicada de Refactoring

    big = obras["/works/OL1W"]
    assert big["titulo"] == big["titulo_exibicao"] == "Big Book: Of Code"
    assert big["autores"] == ["Ana B. Autora"]  # a forma mais completa, uma vez só
    assert (big["edicoes_ol"], big["popularidade"], big["curada"]) == (10, 0, False)

    fluent = obras["/works/OL2W"]
    # A Edição em português, com o subtítulo dela, como o título da work.
    assert fluent["titulo_exibicao"] == "Fluente: programando com estilo"
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
    conexao: Connection, dumps: Path, curados: Path, separadas: Path, catalogo: dict[str, int]
) -> None:
    """§8.8, passo 7: o corte escolhe candidatas a Sugestão; a Obra que o Leitor já tem
    vira técnica pelo assunto. A work de ficção (ruído) continua de fora."""
    antigo = criar_obra(conexao, "Antigo", ol_work_key="/works/OL5W", origem="leitor")
    robos = criar_obra(conexao, "Robos", ol_work_key="/works/OL7W", origem="leitor")

    r = carregar_tecnicas(conexao, dumps, curados=curados, separadas=separadas)

    assert antigo in _tecnicas(conexao)
    assert robos not in _tecnicas(conexao)
    assert r.do_leitor == 2  # Antigo e Do Leitor
    assert "/works/OL5W" not in _obras(conexao)


def test_obra_do_leitor_de_biografias_nao_vira_tecnica(
    conexao: Connection, dumps: Path, curados: Path, separadas: Path, catalogo: dict[str, int]
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

    r = carregar_tecnicas(conexao, dumps, curados=curados, separadas=separadas)

    assert catalogo["leitor"] not in _tecnicas(conexao)
    assert r.do_leitor == 0


def test_inteligencia_artificial_sozinha_nao_faz_obra_tecnica() -> None:
    """Anais, divulgação e biografias (Superinteligência, O homem que sabia demais) só têm
    "Artificial intelligence"; os livros de IA de verdade têm também outro assunto técnico."""
    criterio = ler_criterio()
    assert not criterio.tecnica(["artificial intelligence"])
    assert not criterio.tecnica(["artificial intelligence -- philosophy"])
    assert criterio.tecnica(["artificial intelligence", "machine learning"])


def test_carga_e_idempotente(
    conexao: Connection, dumps: Path, curados: Path, separadas: Path, catalogo: dict[str, int]
) -> None:
    carregar_tecnicas(conexao, dumps, curados=curados, separadas=separadas)
    ids = {k: o["id"] for k, o in _obras(conexao).items()}

    r = carregar_tecnicas(conexao, dumps, curados=curados, separadas=separadas)

    assert {k: o["id"] for k, o in _obras(conexao).items()} == ids
    assert (r.novas, r.apagadas) == (0, 0)


def test_obra_fora_do_corte_sai_se_ninguem_usa(
    conexao: Connection,
    dumps: Path,
    curados: Path,
    separadas: Path,
    catalogo: dict[str, int],
    tmp_path: Path,
) -> None:
    carregar_tecnicas(conexao, dumps, curados=curados, separadas=separadas)
    fluent = _obras(conexao)["/works/OL2W"]["id"]
    conexao.execute(
        text("INSERT INTO quero_ler (leitor_id, obra_id) VALUES (:l, :o)"),
        {"l": LEITOR_ID, "o": fluent},
    )
    sem_editoras = tmp_path / "editoras.txt"
    sem_editoras.write_text("nenhuma editora assim\n", encoding="utf-8")

    r = carregar_tecnicas(
        conexao, dumps, curados=curados, separadas=separadas, editoras=sem_editoras
    )

    # Fluent Thing e Lançamento saem do corte: a primeira está em Quero ler e fica.
    assert set(_obras(conexao)) == {"/works/OL1W", "/works/OL2W", "/works/OL10W"}
    assert (r.apagadas, r.mantidas_em_uso) == (1, 1)
    assert fluent in _tecnicas(conexao)


def test_obra_mantida_fora_do_corte_continua_com_isbns_e_assuntos(
    conexao: Connection,
    dumps: Path,
    curados: Path,
    separadas: Path,
    catalogo: dict[str, int],
    tmp_path: Path,
) -> None:
    carregar_tecnicas(conexao, dumps, curados=curados, separadas=separadas)
    fluent = _obras(conexao)["/works/OL2W"]["id"]
    conexao.execute(
        text("INSERT INTO quero_ler (leitor_id, obra_id) VALUES (:l, :o)"),
        {"l": LEITOR_ID, "o": fluent},
    )
    sem_editoras = tmp_path / "editoras.txt"
    sem_editoras.write_text("nenhuma editora assim\n", encoding="utf-8")

    carregar_tecnicas(conexao, dumps, curados=curados, separadas=separadas, editoras=sem_editoras)

    # A Obra fica "sem os dados da carga anterior mudarem" (SPEC §8.8, passo 8).
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
    conexao: Connection, dumps: Path, separadas: Path, tmp_path: Path, item: str, mensagem: str
) -> None:
    sincronizar_generos(conexao)
    caminho = tmp_path / "ruim.yaml"
    caminho.write_text(item, encoding="utf-8")
    with pytest.raises(CuradaInvalida, match=mensagem):
        carregar_tecnicas(conexao, dumps, curados=caminho, separadas=separadas)


def test_lista_curada_do_projeto_e_valida() -> None:
    from recomendador.pipeline.tecnicas import ler_curados

    curadas = ler_curados()
    assert len(curadas) >= 60
    assert all(c.work.startswith("/works/OL") and c.titulo and c.autor for c in curadas)


# --- Works duplicadas da mesma Obra, juntadas pelo título e pelo autor ---

_PACKT = {"editora": "Packt Publishing", "ano": "2019"}
ISBN_SEGUNDA = completar_isbn13("978178439277")  # da work da 2ª edição


def _carregar_so(
    conexao: Connection,
    tmp_path: Path,
    works: list,
    edicoes: list,
    curados: str = "",
    separadas: str = "",
):
    pasta = tmp_path / "ol"
    pasta.mkdir(parents=True)
    _dump(pasta / "ol_dump_works_2026-10-31.txt.gz", "work", [(w["key"], w) for w in works])
    _dump(
        pasta / "ol_dump_editions_2026-10-31.txt.gz",
        "edition",
        [(f"/books/OL{i}M", e) for i, e in enumerate(edicoes, 1)],
    )
    nomes = {
        "/authors/OL1A": "Willi Richert",
        "/authors/OL2A": "Luis Pedro Coelho",
        "/authors/OL3A": "Matthieu Brucher",
        "/authors/OL4A": "Luis P. Coelho",  # outro registro do mesmo autor
        "/authors/OL5A": "Ethem Alpaydin",
        "/authors/OL6A": "Tom Mitchell",
        "/authors/OL7A": "Martin Fowler",
    }
    _dump(
        pasta / "ol_dump_authors_2026-10-31.txt.gz",
        "author",
        [(k, {"key": k, "name": n}) for k, n in nomes.items()],
    )
    lista = tmp_path / "curados.yaml"
    lista.write_text(curados, encoding="utf-8")
    lista_separadas = tmp_path / "separadas.yaml"
    lista_separadas.write_text(separadas, encoding="utf-8")
    sincronizar_generos(conexao)
    return carregar_tecnicas(conexao, pasta, curados=lista, separadas=lista_separadas)


def test_edicoes_da_mesma_obra_viram_uma_obra(conexao: Connection, tmp_path: Path) -> None:
    """Na Open Library, cada edição de *Building Machine Learning Systems with Python* é
    uma work. Mesmo título, sem a marca de edição, e um autor em comum: uma Obra só, a da
    work de mais Edições, com as Edições e os ISBNs de todas."""
    works = [
        _work(
            "/works/OL20W",
            "Building Machine Learning Systems with Python",
            TECNICO,
            autor=("/authors/OL1A", "/authors/OL2A"),
        ),
        _work(
            "/works/OL21W",
            "Building Machine Learning Systems with Python",
            TECNICO,
            autor=("/authors/OL2A", "/authors/OL1A", "/authors/OL3A"),
            subtitle="Explore machine learning and deep learning techniques, 3rd Edition",
        ),
        _work(
            "/works/OL22W",
            "Building Machine Learning Systems with Python - Second Edition",
            TECNICO,
            autor="/authors/OL4A",
        ),
    ]
    edicoes = (
        _edicoes("/works/OL20W", 3, **_PACKT)
        + _edicoes("/works/OL21W", 1, **_PACKT)
        + _edicoes("/works/OL22W", 2, isbn_13=[ISBN_SEGUNDA], **_PACKT)
    )

    r = _carregar_so(conexao, tmp_path, works, edicoes)

    obras = _obras(conexao)
    assert set(obras) == {"/works/OL20W"}
    assert obras["/works/OL20W"]["edicoes_ol"] == 6
    assert r.fundidas == 2
    isbn = conexao.execute(
        text("SELECT obra_id FROM obra_isbn WHERE isbn13 = :i"), {"i": ISBN_SEGUNDA}
    ).scalar_one()
    assert isbn == obras["/works/OL20W"]["id"]


def test_obras_diferentes_de_mesmo_titulo_continuam_separadas(
    conexao: Connection, tmp_path: Path
) -> None:
    works = [
        # Mesmo título, autores diferentes.
        _work("/works/OL30W", "Machine Learning", TECNICO, autor="/authors/OL5A"),
        _work("/works/OL31W", "Machine Learning", TECNICO, autor="/authors/OL6A"),
        # Volumes da mesma série.
        _work(
            "/works/OL32W",
            "Deep Belief Nets: Volume 1: Restricted Boltzmann Machines",
            TECNICO,
            autor="/authors/OL5A",
        ),
        _work(
            "/works/OL33W",
            "Deep Belief Nets",
            TECNICO,
            autor="/authors/OL5A",
            subtitle="Volume 2: Autoencoding",
        ),
        # Subtítulos diferentes: livros diferentes do mesmo autor.
        _work(
            "/works/OL34W", "Starting Out", TECNICO, autor="/authors/OL6A", subtitle="Early Objects"
        ),
        _work(
            "/works/OL35W",
            "Starting Out",
            TECNICO,
            autor="/authors/OL6A",
            subtitle="From Control Structures through Objects",
        ),
    ]
    edicoes = [e for w in works for e in _edicoes(w["key"], 2, **_PACKT)]

    r = _carregar_so(conexao, tmp_path, works, edicoes)

    assert set(_obras(conexao)) == {w["key"] for w in works}
    assert r.fundidas == 0


def test_work_da_lista_curada_absorve_a_duplicada_do_corte(
    conexao: Connection, tmp_path: Path
) -> None:
    """A work curada fica, mesmo com menos Edições; a do corte vira só Edições dela."""
    works = [
        _work("/works/OL40W", "Refactoring", ["Object oriented"], autor="/authors/OL7A"),
        _work(
            "/works/OL41W",
            "Refactoring",
            TECNICO,
            autor="/authors/OL7A",
            subtitle="Improving the Design of Existing Code, 2nd edition",
        ),
    ]
    edicoes = _edicoes("/works/OL40W", 1, **_PACKT) + _edicoes("/works/OL41W", 12)
    curados = "- work: /works/OL40W\n  titulo: Refactoring\n  autor: Martin Fowler\n"

    r = _carregar_so(conexao, tmp_path, works, edicoes, curados)

    obras = _obras(conexao)
    assert set(obras) == {"/works/OL40W"}
    assert (obras["/works/OL40W"]["edicoes_ol"], obras["/works/OL40W"]["curada"]) == (13, True)
    assert r.fundidas == 1


def _angularjs() -> tuple[list, list]:
    """*AngularJS* (2013) e *AngularJS: Up and Running* (2015): livros diferentes dos mesmos
    autores, que a regra do título juntaria porque um deles não tem subtítulo."""
    works = [
        _work("/works/OL60W", "AngularJS", TECNICO, autor="/authors/OL6A"),
        _work(
            "/works/OL61W",
            "AngularJS",
            TECNICO,
            autor="/authors/OL6A",
            subtitle="Up and Running",
        ),
    ]
    return works, [e for w in works for e in _edicoes(w["key"], 3, **_PACKT)]


def test_work_da_lista_de_separadas_nao_se_junta_pelo_titulo(
    conexao: Connection, tmp_path: Path
) -> None:
    works, edicoes = _angularjs()
    separadas = "- work: /works/OL60W\n  titulo: AngularJS\n  autor: Tom Mitchell\n"

    r = _carregar_so(conexao, tmp_path, works, edicoes, separadas=separadas)

    obras = _obras(conexao)
    assert set(obras) == {"/works/OL60W", "/works/OL61W"}
    assert not any(o["curada"] for o in obras.values())  # não passa na frente na Montagem
    assert r.fundidas == 0


def test_sem_a_lista_de_separadas_as_duas_viram_uma(conexao: Connection, tmp_path: Path) -> None:
    works, edicoes = _angularjs()

    r = _carregar_so(conexao, tmp_path, works, edicoes)

    assert len(_obras(conexao)) == 1
    assert r.fundidas == 1


@pytest.mark.parametrize(
    ("item", "mensagem"),
    [
        ("- {work: /works/OL99W, titulo: Sumida, autor: X}", "não está no dump"),
        ("- {work: /works/OL60W, titulo: Outro Livro, autor: X}", "não começa por"),
    ],
)
def test_lista_de_separadas_invalida(
    conexao: Connection, tmp_path: Path, item: str, mensagem: str
) -> None:
    works, edicoes = _angularjs()
    with pytest.raises(CuradaInvalida, match=mensagem):
        _carregar_so(conexao, tmp_path, works, edicoes, separadas=item)


def test_lista_de_separadas_do_projeto_e_valida() -> None:
    from recomendador.pipeline.tecnicas import ler_curados, ler_separadas

    separadas = ler_separadas()
    assert any(s.work == "/works/OL19548384W" for s in separadas)  # AngularJS (2013)
    assert all(s.work.startswith("/works/OL") and s.titulo and s.autor for s in separadas)
    assert not {s.work for s in separadas} & {c.work for c in ler_curados()}


def test_c_e_cpp_sao_obras_diferentes(conexao: Connection, tmp_path: Path) -> None:
    works = [
        _work("/works/OL50W", "C How to Program", TECNICO, autor="/authors/OL6A"),
        _work("/works/OL51W", "C++ How to Program", TECNICO, autor="/authors/OL6A"),
        _work("/works/OL52W", "C# How to Program", TECNICO, autor="/authors/OL6A"),
    ]
    edicoes = [e for w in works for e in _edicoes(w["key"], 2, **_PACKT)]

    _carregar_so(conexao, tmp_path, works, edicoes)

    assert set(_obras(conexao)) == {w["key"] for w in works}


def test_obra_da_work_absorvida_e_fundida_na_que_fica(conexao: Connection, tmp_path: Path) -> None:
    """A Obra de uma work que uma carga anterior gravou e esta absorve (*Machine Learning,
    Revised and Updated Edition* em *Machine learning*) é fundida na que fica, como na
    fusão do goodbooks: o que o Leitor tinha nela passa, com os ISBNs, e ela sai."""
    segunda = _work(
        "/works/OL61W",
        "Building Machine Learning Systems with Python - Second Edition",
        TECNICO,
        autor="/authors/OL2A",
    )
    primeira = _work(
        "/works/OL60W",
        "Building Machine Learning Systems with Python",
        TECNICO,
        autor="/authors/OL2A",
    )
    edicoes_segunda = _edicoes("/works/OL61W", 2, isbn_13=[ISBN_SEGUNDA], **_PACKT)
    _carregar_so(conexao, tmp_path / "1", [segunda], edicoes_segunda)
    absorvida = _obras(conexao)["/works/OL61W"]["id"]
    conexao.execute(
        text("INSERT INTO evento (leitor_id, tipo, obra_id) VALUES (:l, 'sugestao_exibida', :o)"),
        {"l": LEITOR_ID, "o": absorvida},
    )
    conexao.execute(
        text("INSERT INTO leitura (leitor_id, obra_id, nota, origem) VALUES (:l, :o, 4, 'busca')"),
        {"l": LEITOR_ID, "o": absorvida},
    )

    r = _carregar_so(
        conexao,
        tmp_path / "2",
        [primeira, segunda],
        _edicoes("/works/OL60W", 3, **_PACKT) + edicoes_segunda,
    )

    obras = _obras(conexao)
    assert set(obras) == {"/works/OL60W"}
    fica = obras["/works/OL60W"]["id"]
    assert (r.mantidas_em_uso, r.obras_fundidas) == (0, 1)
    for tabela in ("evento", "leitura"):
        assert conexao.execute(text(f"SELECT obra_id FROM {tabela}")).scalars().all() == [fica]
    assert (
        conexao.execute(
            text("SELECT obra_id FROM obra_isbn WHERE isbn13 = :i"), {"i": ISBN_SEGUNDA}
        ).scalar_one()
        == fica
    )
    assert fica in _tecnicas(conexao)


def test_titulo_da_edicao_do_leitor_continua_depois_da_carga(
    conexao: Connection, dumps: Path, curados: Path, separadas: Path, catalogo: dict[str, int]
) -> None:
    """A Edição brasileira que o Leitor gravou deu o título à Obra (§7.2). Sem Edição em
    português no dump, a carga seguinte não volta ao título em inglês."""
    carregar_tecnicas(conexao, dumps, curados=curados, separadas=separadas)
    big = _obras(conexao)["/works/OL1W"]["id"]
    conexao.execute(
        text(
            "INSERT INTO edicao (obra_id, titulo, idioma) "
            "VALUES (:o, 'Livrão: do código (Em Portugues do Brasil)', 'pt')"
        ),
        {"o": big},
    )
    conexao.execute(
        text("UPDATE obra SET titulo_exibicao = 'Livrão: do código' WHERE id = :o"), {"o": big}
    )

    carregar_tecnicas(conexao, dumps, curados=curados, separadas=separadas)

    obras = _obras(conexao)
    assert obras["/works/OL1W"]["titulo_exibicao"] == "Livrão: do código"
    assert obras["/works/OL1W"]["tem_edicao_pt"] is True
    # A do dump continua valendo onde existe.
    assert obras["/works/OL2W"]["titulo_exibicao"] == "Fluente: programando com estilo"
