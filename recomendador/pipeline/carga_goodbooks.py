"""Carga do goodbooks-10k no Catálogo (SPEC §6.1). Idempotente: upsert por `goodbooks_book_id`."""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from sqlalchemy import Connection, and_, delete, select
from sqlalchemy.dialects.postgresql import insert

from recomendador.catalogo.isbn import completar_isbn13, normalizar_isbn
from recomendador.catalogo.tags import tag_util
from recomendador.db.modelos import Obra, ObraIsbn, ObraTag, OrigemObra

log = logging.getLogger(__name__)

TAGS_POR_OBRA = 30
ARQUIVO_NOTAS = "notas.parquet"

COLUNAS = {
    "books.csv": {
        "book_id",
        "goodreads_book_id",
        "isbn",
        "isbn13",
        "authors",
        "original_publication_year",
        "original_title",
        "title",
        "work_ratings_count",
        "image_url",
    },
    "ratings.csv": {"user_id", "book_id", "rating"},
    "book_tags.csv": {"goodreads_book_id", "tag_id", "count"},
    "tags.csv": {"tag_id", "tag_name"},
}

# "The Hunger Games (The Hunger Games, #1)" → "The Hunger Games". Só sufixos com "#",
# para não cortar parênteses que fazem parte do título ("I Am America (And So Can You!)").
_SUFIXO_DE_SERIE = re.compile(r"\s*\([^()]*#[^()]*\)\s*$")


class ArquivoInvalido(ValueError):
    """Um CSV da Base de coleitura não tem as colunas esperadas."""


@dataclass(frozen=True)
class ResumoCarga:
    obras: int
    isbns: int
    tags: int
    notas: int


def _ler_csv(pasta: Path, nome: str, **kwargs) -> pd.DataFrame:
    caminho = pasta / nome
    df = pd.read_csv(caminho, **kwargs)
    faltando = COLUNAS[nome] - set(df.columns)
    if faltando:
        raise ArquivoInvalido(
            f"{caminho}: faltam as colunas {sorted(faltando)}; "
            f"encontradas: {sorted(df.columns)}. O formato do goodbooks-10k mudou?"
        )
    return df


def _texto(valor: object) -> str | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    s = str(valor).strip()
    return s or None


def limpar_titulo(titulo: str) -> str:
    return _SUFIXO_DE_SERIE.sub("", titulo).strip() or titulo.strip()


def isbn13_do_goodbooks(isbn10: object, isbn13: object) -> set[str]:
    """Os dois ISBNs de uma linha de books.csv, normalizados para ISBN-13.

    O CSV perdeu os zeros à esquerda do ISBN-10 e gravou o ISBN-13 em notação científica
    ("9.78043902348e+12"), sem o dígito verificador. Os 12 primeiros dígitos sobrevivem,
    então o dígito verificador é recalculado.
    """
    isbns: set[str] = set()
    if (s := _texto(isbn10)) and re.fullmatch(r"\d{6,9}[\dXx]", s):
        if n := normalizar_isbn(s.zfill(10)):
            isbns.add(n)
    if s := _texto(isbn13):
        try:
            digitos = str(int(Decimal(s)))
        except (InvalidOperation, ValueError):
            digitos = ""
        if len(digitos) == 13 and digitos.startswith(("978", "979")):
            isbns.add(completar_isbn13(digitos[:12]))
    return isbns


def _linhas_de_obra(books: pd.DataFrame) -> list[dict]:
    linhas = []
    for b in books.itertuples(index=False):
        titulo = limpar_titulo(str(b.title))
        capa = _texto(b.image_url)
        ano = _texto(b.original_publication_year)
        linhas.append(
            {
                "goodbooks_book_id": int(b.book_id),
                "titulo": titulo,
                "titulo_original": _texto(b.original_title),
                "titulo_exibicao": titulo,
                "autores": [a.strip() for a in str(b.authors).split(",") if a.strip()],
                "ano_original": int(float(ano)) if ano else None,
                "capa_url": None if capa is None or "nophoto" in capa else capa,
                "popularidade": int(b.work_ratings_count),
                "origem": OrigemObra.BASE,
            }
        )
    return linhas


def _upsert_obras(conn: Connection, linhas: list[dict]) -> dict[int, int]:
    """Grava as Obras e devolve goodbooks_book_id → obra.id.

    No conflito, só atualiza o que vem do goodbooks-10k: `titulo_exibicao`, `descricao`
    e `ol_work_key` são do enriquecimento (§6.2) e ficam como estão.
    """
    stmt = insert(Obra)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Obra.goodbooks_book_id],
        set_={
            c: stmt.excluded[c]
            for c in ("titulo", "titulo_original", "autores", "ano_original", "capa_url")
        }
        | {"popularidade": stmt.excluded.popularidade},
    )
    conn.execute(stmt, linhas)
    ids = [linha["goodbooks_book_id"] for linha in linhas]
    return dict(
        conn.execute(
            select(Obra.goodbooks_book_id, Obra.id).where(Obra.goodbooks_book_id.in_(ids))
        ).all()
    )


def _linhas_de_tag(
    book_tags: pd.DataFrame, tags: pd.DataFrame, books: pd.DataFrame, obra_por_gb: dict[int, int]
) -> list[dict]:
    """Top tags úteis por Obra. book_tags usa o id do Goodreads, não o `book_id`."""
    nomes = tags.assign(tag=tags["tag_name"].astype(str).str.strip().str.lower())
    nomes = nomes[nomes["tag"].map(tag_util)]
    df = book_tags.merge(nomes[["tag_id", "tag"]], on="tag_id")
    df = df[df["count"] > 0]
    gr_para_gb = dict(zip(books["goodreads_book_id"], books["book_id"], strict=True))
    df = df.assign(obra_id=df["goodreads_book_id"].map(gr_para_gb).map(obra_por_gb))
    df = df.dropna(subset=["obra_id"])
    # Há pares (livro, tag) repetidos e tags distintas que viram iguais após lower().
    df = df.groupby(["obra_id", "tag"], as_index=False)["count"].max()
    df = df.sort_values(["obra_id", "count", "tag"], ascending=[True, False, True])
    df = df.groupby("obra_id").head(TAGS_POR_OBRA)
    return [
        {"obra_id": int(o), "tag": t, "contagem": int(c)}
        for o, t, c in zip(df["obra_id"], df["tag"], df["count"], strict=True)
    ]


def _gravar_notas(pasta: Path, obras_conhecidas: set[int]) -> int:
    notas = _ler_csv(pasta, "ratings.csv")
    notas = notas.rename(
        columns={"user_id": "usuario_base", "book_id": "goodbooks_book_id", "rating": "nota"}
    )[["usuario_base", "goodbooks_book_id", "nota"]]
    notas = notas[notas["goodbooks_book_id"].isin(obras_conhecidas)]
    notas = notas.astype({"usuario_base": "int32", "goodbooks_book_id": "int32", "nota": "int8"})
    destino = pasta / ARQUIVO_NOTAS
    parcial = destino.with_suffix(".parquet.parcial")
    notas.to_parquet(parcial, index=False)
    parcial.replace(destino)
    return len(notas)


def carregar_base(conn: Connection, pasta: Path) -> ResumoCarga:
    """Carrega `books`, `tags` e `book_tags` no banco e grava `notas.parquet` em `pasta`."""
    books = _ler_csv(pasta, "books.csv", dtype={"isbn": str, "isbn13": str})
    tags = _ler_csv(pasta, "tags.csv", keep_default_na=False)
    book_tags = _ler_csv(pasta, "book_tags.csv")

    obra_por_gb = _upsert_obras(conn, _linhas_de_obra(books))
    log.info("%d Obras gravadas", len(obra_por_gb))

    isbns = [
        {"isbn13": isbn, "obra_id": obra_por_gb[int(b.book_id)]}
        for b in books.itertuples(index=False)
        for isbn in isbn13_do_goodbooks(b.isbn, b.isbn13)
    ]
    if isbns:
        conn.execute(insert(ObraIsbn).on_conflict_do_nothing(), isbns)

    linhas_tag = _linhas_de_tag(book_tags, tags, books, obra_por_gb)
    # Troca as tags de leitores; os assuntos da Open Library (contagem = 0) ficam.
    conn.execute(
        delete(ObraTag).where(
            and_(ObraTag.contagem > 0, ObraTag.obra_id.in_(list(obra_por_gb.values())))
        )
    )
    stmt = insert(ObraTag)
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[ObraTag.obra_id, ObraTag.tag],
            set_={"contagem": stmt.excluded.contagem},
        ),
        linhas_tag,
    )
    log.info("%d ISBNs e %d tags de Obra", len(isbns), len(linhas_tag))

    n_notas = _gravar_notas(pasta, set(obra_por_gb))
    log.info("%d Notas da Base de coleitura em %s", n_notas, pasta / ARQUIVO_NOTAS)
    return ResumoCarga(
        obras=len(obra_por_gb), isbns=len(isbns), tags=len(linhas_tag), notas=n_notas
    )
