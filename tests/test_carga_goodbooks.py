"""`carregar-base` sobre a amostra de 200 Obras / 2 mil Notas (SPEC §6.1, §12)."""

import shutil
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Connection, text

from recomendador.config import LEITOR_ID
from recomendador.pipeline.carga_goodbooks import (
    ArquivoInvalido,
    Fusao,
    carregar_base,
    isbn13_do_goodbooks,
    limpar_titulo,
)

MINI = Path(__file__).parent / "dados" / "goodbooks-mini"


@pytest.fixture
def pasta(tmp_path: Path) -> Path:
    destino = tmp_path / "raw"
    shutil.copytree(MINI, destino)
    return destino


def _obra(conexao: Connection, goodbooks_book_id: int) -> dict:
    return dict(
        conexao.execute(
            text("SELECT * FROM obra WHERE goodbooks_book_id = :g"), {"g": goodbooks_book_id}
        )
        .mappings()
        .one()
    )


def _isbns(conexao: Connection, obra_id: int) -> set[str]:
    return set(
        conexao.execute(
            text("SELECT isbn13 FROM obra_isbn WHERE obra_id = :o"), {"o": obra_id}
        ).scalars()
    )


def test_cada_livro_vira_uma_obra_da_base(conexao: Connection, pasta: Path) -> None:
    resumo = carregar_base(conexao, pasta)

    assert resumo.obras == 200
    origens = conexao.execute(text("SELECT origem, count(*) FROM obra GROUP BY 1")).all()
    assert [(str(o), n) for o, n in origens] == [("base", 200)]


def test_campos_da_obra(conexao: Connection, pasta: Path) -> None:
    carregar_base(conexao, pasta)

    jogos = _obra(conexao, 1)
    assert jogos["titulo"] == "The Hunger Games"  # sem "(The Hunger Games, #1)"
    assert jogos["titulo_exibicao"] == "The Hunger Games"
    assert jogos["titulo_original"] == "The Hunger Games"
    assert jogos["autores"] == ["Suzanne Collins"]
    assert jogos["ano_original"] == 2008
    assert jogos["popularidade"] == 4942365
    assert jogos["capa_url"].startswith("https://images.gr-assets.com/")

    azkaban = _obra(conexao, 18)
    assert azkaban["autores"] == ["J.K. Rowling", "Mary GrandPré", "Rufus Beck"]

    assert _obra(conexao, 33)["capa_url"] is None  # placeholder "nophoto"
    assert _obra(conexao, 79)["ano_original"] == -720  # Odisseia
    assert _obra(conexao, 123)["titulo"] == "The Firm (Penguin Readers, Level 5)"


def test_isbns_normalizados_para_13(conexao: Connection, pasta: Path) -> None:
    carregar_base(conexao, pasta)

    assert _isbns(conexao, _obra(conexao, 1)["id"]) == {"9780439023481"}
    assert _isbns(conexao, _obra(conexao, 4)["id"]) == {"9780061120084"}  # zero perdido
    assert _isbns(conexao, _obra(conexao, 18)["id"]) == {"9780439655484"}  # ISBN-10 com X
    assert _isbns(conexao, _obra(conexao, 106)["id"]) == set()  # sem ISBN no CSV


def test_isbn_da_base_toma_o_lugar_de_um_da_open_library(conexao: Connection, pasta: Path) -> None:
    """Um ISBN da Base que uma execução do `enriquecer-ol` pôs em outra Obra volta para a
    Obra da Base, com origem `base` (o `enriquecer-ol` apaga os de origem `open_library`)."""
    carregar_base(conexao, pasta)
    jogos, outra = _obra(conexao, 1)["id"], _obra(conexao, 4)["id"]
    conexao.execute(
        text("UPDATE obra_isbn SET obra_id = :o, origem = 'open_library' WHERE isbn13 = :i"),
        {"o": outra, "i": "9780439023481"},
    )

    carregar_base(conexao, pasta)

    obra_id, origem = conexao.execute(
        text("SELECT obra_id, origem FROM obra_isbn WHERE isbn13 = '9780439023481'")
    ).one()
    assert (obra_id, str(origem)) == (jogos, "base")


def test_isbn13_em_notacao_cientifica_recupera_o_digito_verificador() -> None:
    # 978043902347|4 não arredondaria para ...348: só sobra 9780439023481.
    assert isbn13_do_goodbooks(None, "9.78043902348e+12") == {"9780439023481"}
    # 978044657980|3 e 978044657979|7 dão os dois "9.7804465798e+12": sem ISBN-10, nenhum.
    assert isbn13_do_goodbooks(None, "9.7804465798e+12") == set()
    assert isbn13_do_goodbooks("446579807", "9.7804465798e+12") == {"9780446579803"}
    assert isbn13_do_goodbooks(None, "9780439023481") == {"9780439023481"}  # inteiro
    assert isbn13_do_goodbooks(None, "76783609419.0") == set()  # não é ISBN
    assert isbn13_do_goodbooks("61120081", None) == {"9780061120084"}


def test_isbn13_arredondado_nao_vira_o_isbn_de_outro_livro() -> None:
    """*A Tree Grows in Brooklyn* (9780061120077) foi gravado como "9.78006112008e+12", e
    recalcular o dígito verificador dava 9780061120084, de *To Kill a Mockingbird*."""
    assert isbn13_do_goodbooks("61120073", "9.78006112008e+12") == {"9780061120077"}
    assert isbn13_do_goodbooks("61120081", "9.78006112008e+12") == {"9780061120084"}
    # Um ISBN-13 que não é o ISBN-10 arredondado é de outra Edição e entra também.
    assert isbn13_do_goodbooks("446612707", "9.78055381395e+12") == {
        "9780446612708",
        "9780553813951",
    }


def test_carga_apaga_os_isbns_da_base_que_o_csv_nao_da_mais(
    conexao: Connection, pasta: Path
) -> None:
    carregar_base(conexao, pasta)
    jogos = _obra(conexao, 1)["id"]
    for isbn, origem in (("9780061120077", "base"), ("9780000000001", "leitor")):
        conexao.execute(
            text("INSERT INTO obra_isbn VALUES (:i, :o, :g)"), {"i": isbn, "o": jogos, "g": origem}
        )

    carregar_base(conexao, pasta)

    assert _isbns(conexao, jogos) == {"9780439023481", "9780000000001"}


def test_limpar_titulo() -> None:
    assert limpar_titulo("Dune (Dune Chronicles, #1)") == "Dune"
    assert limpar_titulo("I Am America (And So Can You!)") == "I Am America (And So Can You!)"


def test_tags_uteis_ate_30_por_obra(conexao: Connection, pasta: Path) -> None:
    carregar_base(conexao, pasta)

    por_obra = conexao.execute(
        text("SELECT max(n), min(n) FROM (SELECT count(*) n FROM obra_tag GROUP BY obra_id) x")
    ).one()
    assert por_obra == (30, 30)
    ignoradas = conexao.execute(
        text(
            "SELECT count(*) FROM obra_tag WHERE tag IN ('to-read', 'favorites', 'owned') "
            "OR tag ~ '(19|20)[0-9]{2}' OR contagem <= 0"
        )
    ).scalar_one()
    assert ignoradas == 0
    tags = set(
        conexao.execute(
            text("SELECT tag FROM obra_tag WHERE obra_id = :o"), {"o": _obra(conexao, 1)["id"]}
        ).scalars()
    )
    assert {"young-adult", "dystopia", "fiction"} <= tags


def test_notas_viram_parquet(conexao: Connection, pasta: Path) -> None:
    resumo = carregar_base(conexao, pasta)

    notas = pd.read_parquet(pasta / "notas.parquet")
    assert list(notas.columns) == ["usuario_base", "goodbooks_book_id", "nota"]
    assert len(notas) == resumo.notas == 2000
    assert notas["nota"].between(1, 5).all()


def test_carga_e_idempotente(conexao: Connection, pasta: Path) -> None:
    def contagens() -> tuple[int, ...]:
        return conexao.execute(
            text(
                "SELECT (SELECT count(*) FROM obra), (SELECT count(*) FROM obra_isbn), "
                "(SELECT count(*) FROM obra_tag)"
            )
        ).one()

    primeira = carregar_base(conexao, pasta)
    antes = contagens()
    # O enriquecimento muda o título de exibição e acrescenta assuntos; a recarga preserva.
    obra_id = _obra(conexao, 1)["id"]
    conexao.execute(
        text("UPDATE obra SET titulo_exibicao = 'Jogos Vorazes' WHERE id = :o"), {"o": obra_id}
    )
    conexao.execute(
        text("INSERT INTO obra_tag VALUES (:o, 'reality television programs', 0)"),
        {"o": obra_id},
    )

    segunda = carregar_base(conexao, pasta)

    assert segunda == primeira
    assert contagens() == (antes[0], antes[1], antes[2] + 1)
    assert _obra(conexao, 1)["titulo_exibicao"] == "Jogos Vorazes"


def test_coluna_faltando_falha_com_mensagem_clara(conexao: Connection, pasta: Path) -> None:
    books = pd.read_csv(pasta / "books.csv").rename(columns={"original_title": "titulo"})
    books.to_csv(pasta / "books.csv", index=False)

    with pytest.raises(
        ArquivoInvalido, match=r"books\.csv: faltam as colunas \['original_title'\]"
    ):
        carregar_base(conexao, pasta)


# --- Fusão de duplicatas do goodbooks-10k (SPEC §6.1) ---

# No mini, o livro 7 (The Hobbit) faz o papel da duplicada e o 2 (Harry Potter), o da que fica.
FUSAO = Fusao(duplicada=7, fica=2, titulo="Harry Potter")


def _leitura(conexao: Connection, obra_id: int, nota: int) -> None:
    conexao.execute(
        text("INSERT INTO leitura (leitor_id, obra_id, nota, origem) VALUES (:l, :o, :n, 'busca')"),
        {"l": LEITOR_ID, "o": obra_id, "n": nota},
    )


def test_fusao_junta_a_duplicada_na_que_fica(conexao: Connection, pasta: Path) -> None:
    carregar_base(conexao, pasta, fusoes=())  # o banco de antes da fusão
    duplicada, fica = _obra(conexao, 7), _obra(conexao, 2)
    isbns_da_duplicada = _isbns(conexao, duplicada["id"])
    _leitura(conexao, duplicada["id"], 5)
    conexao.execute(
        text("INSERT INTO edicao (obra_id, titulo) VALUES (:o, 'O Hobbit')"),
        {"o": duplicada["id"]},
    )
    conexao.execute(
        text("INSERT INTO evento (leitor_id, tipo, obra_id) VALUES (:l, 'teste', :o)"),
        {"l": LEITOR_ID, "o": duplicada["id"]},
    )
    antes = pd.read_parquet(pasta / "notas.parquet")

    resumo = carregar_base(conexao, pasta, fusoes=(FUSAO,))

    assert (
        conexao.execute(
            text("SELECT count(*) FROM obra WHERE goodbooks_book_id = 7 OR id = :o"),
            {"o": duplicada["id"]},
        ).scalar_one()
        == 0
    )
    depois = _obra(conexao, 2)
    assert depois["id"] == fica["id"]
    assert depois["popularidade"] == fica["popularidade"] + duplicada["popularidade"]
    assert (depois["titulo"], depois["titulo_exibicao"]) == ("Harry Potter", "Harry Potter")
    assert isbns_da_duplicada <= _isbns(conexao, fica["id"])
    # O que o Leitor tinha na duplicada passa para a que fica.
    for tabela in ("leitura", "edicao", "evento"):
        assert conexao.execute(text(f"SELECT obra_id FROM {tabela}")).scalars().all() == [
            fica["id"]
        ]
    assert "fantasy" in set(
        conexao.execute(
            text("SELECT tag FROM obra_tag WHERE obra_id = :o"), {"o": fica["id"]}
        ).scalars()
    )
    # As Notas da duplicada vão para a que fica; quem deu Nota às duas fica com a da que fica.
    notas = pd.read_parquet(pasta / "notas.parquet")
    assert 7 not in set(notas["goodbooks_book_id"])
    em_comum = set(antes[antes.goodbooks_book_id == 7].usuario_base) & set(
        antes[antes.goodbooks_book_id == 2].usuario_base
    )
    assert len(em_comum) == 7
    assert len(notas) == resumo.notas == len(antes) - len(em_comum)
    da_que_fica = antes[antes.goodbooks_book_id == 2].set_index("usuario_base")["nota"]
    juntas = notas[notas.goodbooks_book_id == 2].set_index("usuario_base")["nota"]
    assert juntas[list(em_comum)].equals(da_que_fica[list(em_comum)])
    assert not notas.duplicated(["usuario_base", "goodbooks_book_id"]).any()

    # Rodar de novo não muda nada.
    contagem = conexao.execute(text("SELECT count(*) FROM obra")).scalar_one()
    assert carregar_base(conexao, pasta, fusoes=(FUSAO,)) == resumo
    assert conexao.execute(text("SELECT count(*) FROM obra")).scalar_one() == contagem


def test_fusao_com_as_duas_na_estante_fica_a_leitura_da_que_fica(
    conexao: Connection, pasta: Path
) -> None:
    carregar_base(conexao, pasta, fusoes=())
    _leitura(conexao, _obra(conexao, 7)["id"], 5)
    _leitura(conexao, _obra(conexao, 2)["id"], 3)

    carregar_base(conexao, pasta, fusoes=(FUSAO,))

    assert conexao.execute(text("SELECT obra_id, nota FROM leitura")).all() == [
        (_obra(conexao, 2)["id"], 3)
    ]


def test_fusao_sem_a_duplicada_no_csv_nao_faz_nada(conexao: Connection, pasta: Path) -> None:
    """As fusões reais (257 e 568) não estão no mini."""
    assert carregar_base(conexao, pasta).obras == carregar_base(conexao, pasta, fusoes=()).obras
