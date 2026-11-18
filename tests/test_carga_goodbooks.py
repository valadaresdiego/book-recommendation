"""`carregar-base` sobre a amostra de 200 Obras / 2 mil Notas (SPEC §6.1, §12)."""

import shutil
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Connection, text

from recomendador.pipeline.carga_goodbooks import (
    ArquivoInvalido,
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


def test_isbn13_em_notacao_cientifica_recupera_o_digito_verificador() -> None:
    assert isbn13_do_goodbooks(None, "9.78043902348e+12") == {"9780439023481"}
    assert isbn13_do_goodbooks(None, "9.7804465798e+12") == {"9780446579803"}
    assert isbn13_do_goodbooks(None, "76783609419.0") == set()  # não é ISBN
    assert isbn13_do_goodbooks("61120081", None) == {"9780061120084"}


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
