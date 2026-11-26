"""Carga do goodbooks-10k no Catálogo (SPEC §6.1). Idempotente: upsert por `goodbooks_book_id`.

As entradas duplicadas do goodbooks-10k (`FUSOES`) são fundidas na que fica, a cada carga.
"""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from sqlalchemy import Connection, and_, delete, select, text
from sqlalchemy.dialects.postgresql import insert

from recomendador.catalogo.isbn import completar_isbn13, normalizar_isbn
from recomendador.catalogo.tags import tag_util
from recomendador.db.modelos import Obra, ObraIsbn, ObraTag, OrigemIsbn, OrigemObra
from recomendador.pipeline.fusao import fundir_obra

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


@dataclass(frozen=True)
class Fusao:
    """Duas entradas do goodbooks-10k para o mesmo texto (SPEC §6.1).

    A duplicada não vira Obra: as Notas, os ISBNs, as tags e a popularidade dela vão para a
    que fica, e uma Obra que ela já tinha no banco é fundida na que fica.
    """

    duplicada: int  # book_id que some
    fica: int  # book_id que fica (o que tem work na Open Library)
    titulo: str | None = None  # novo título da que fica, quando o dela é pior


FUSOES = (
    # "Alice in Wonderland" (sem work) → "Alice's Adventures in Wonderland".
    Fusao(duplicada=257, fica=1725),
    # A coletânea (sem work) → a entrada "#1", que ficou com a work da Obra inteira.
    Fusao(duplicada=568, fica=2100, titulo="Batman: The Dark Knight Returns"),
)


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
    """Os ISBNs de uma linha de books.csv, normalizados para ISBN-13.

    O CSV perdeu os zeros à esquerda do ISBN-10 e gravou o ISBN-13 em notação científica
    com 12 algarismos ("9.78006112008e+12"): o dígito verificador sumiu e, quando era 5 ou
    mais, o 12º algarismo foi arredondado para cima. Recalcular o dígito verificador sobre
    os 12 algarismos dava um ISBN errado em 4.204 linhas, muitas vezes o de outro livro da
    mesma editora: *A Tree Grows in Brooklyn* (9780061120077) ficava com o ISBN de
    *To Kill a Mockingbird* (9780061120084).

    - O ISBN-10 é exato. Se ele é um dos ISBN-13 que o arredondamento explica, vale sozinho.
    - Senão, o ISBN-13 do CSV entra só quando o arredondamento deixa um candidato só.
    """
    isbns: set[str] = set()
    if (s := _texto(isbn10)) and re.fullmatch(r"\d{6,9}[\dXx]", s):
        if n := normalizar_isbn(s.zfill(10)):
            isbns.add(n)
    candidatos = _candidatos_do_isbn13(isbn13)
    if isbns & candidatos:
        return isbns
    return isbns | candidatos if len(candidatos) == 1 else isbns


def _candidatos_do_isbn13(valor: object) -> set[str]:
    """Os ISBN-13 válidos que, escritos com 12 algarismos, dão `valor`."""
    if not (s := _texto(valor)):
        return set()
    try:
        numero = Decimal(s)
        digitos = str(int(numero))
    except (InvalidOperation, ValueError):
        return set()
    if len(digitos) != 13 or not digitos.startswith(("978", "979")):
        return set()
    if len(numero.as_tuple().digits) >= 13:  # escrito por inteiro, sem arredondamento
        return {n} if (n := normalizar_isbn(digitos)) else set()
    # O 13º algarismo d foi arredondado (empate para o par): os 12 vêm inteiros se d ≤ 5,
    # e foram somados de 1 se d ≥ 5.
    corpo = int(digitos[:12])
    inteiro, somado = completar_isbn13(str(corpo)), completar_isbn13(str(corpo - 1))
    return {i for i, ok in ((inteiro, inteiro[-1] <= "5"), (somado, somado[-1] >= "5")) if ok}


def _destino(fusoes: tuple[Fusao, ...]) -> dict[int, int]:
    """book_id da duplicada → book_id da que fica."""
    return {f.duplicada: f.fica for f in fusoes}


def _linhas_de_obra(books: pd.DataFrame, fusoes: tuple[Fusao, ...]) -> list[dict]:
    destino = _destino(fusoes)
    titulos = {f.fica: f.titulo for f in fusoes if f.titulo}
    popularidade = (
        books.assign(fica=books["book_id"].map(lambda b: destino.get(int(b), int(b))))
        .groupby("fica")["work_ratings_count"]
        .sum()
    )
    linhas = []
    for b in books.itertuples(index=False):
        if int(b.book_id) in destino:
            continue
        titulo = titulos.get(int(b.book_id)) or limpar_titulo(str(b.title))
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
                "popularidade": int(popularidade[int(b.book_id)]),
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
    """Top tags úteis por Obra. book_tags usa o id do Goodreads, não o `book_id`.

    `obra_por_gb` já leva a duplicada de uma fusão para a Obra que fica."""
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


def _gravar_notas(pasta: Path, obras_conhecidas: set[int], fusoes: tuple[Fusao, ...]) -> int:
    notas = _ler_csv(pasta, "ratings.csv")
    notas = notas.rename(
        columns={"user_id": "usuario_base", "book_id": "goodbooks_book_id", "rating": "nota"}
    )[["usuario_base", "goodbooks_book_id", "nota"]]
    # A Nota dada à duplicada passa para a que fica; quem deu Nota às duas fica com a da
    # que fica (a ordenação estável põe as da duplicada depois).
    destino = _destino(fusoes)
    duplicada = notas["goodbooks_book_id"].isin(list(destino))
    notas = (
        notas.assign(goodbooks_book_id=notas["goodbooks_book_id"].replace(destino), _dup=duplicada)
        .sort_values("_dup", kind="stable")
        .drop_duplicates(["usuario_base", "goodbooks_book_id"])
        .sort_index()
        .drop(columns="_dup")
    )
    notas = notas[notas["goodbooks_book_id"].isin(obras_conhecidas)]
    notas = notas.astype({"usuario_base": "int32", "goodbooks_book_id": "int32", "nota": "int8"})
    destino = pasta / ARQUIVO_NOTAS
    parcial = destino.with_suffix(".parquet.parcial")
    notas.to_parquet(parcial, index=False)
    parcial.replace(destino)
    return len(notas)


def carregar_base(conn: Connection, pasta: Path, fusoes: tuple[Fusao, ...] = FUSOES) -> ResumoCarga:
    """Carrega `books`, `tags` e `book_tags` no banco e grava `notas.parquet` em `pasta`."""
    books = _ler_csv(pasta, "books.csv", dtype={"isbn": str, "isbn13": str})
    tags = _ler_csv(pasta, "tags.csv", keep_default_na=False)
    book_tags = _ler_csv(pasta, "book_tags.csv")

    fusoes = tuple(f for f in fusoes if f.duplicada in set(books["book_id"]))
    obra_por_gb = _upsert_obras(conn, _linhas_de_obra(books, fusoes))
    obras_da_base = len(obra_por_gb)
    log.info("%d Obras gravadas", obras_da_base)
    for f in fusoes:
        _fundir_no_banco(conn, f, obra_por_gb[f.fica])
        log.info("Fusão: goodbooks %d entra na Obra %d", f.duplicada, obra_por_gb[f.fica])
    # Daqui em diante, a duplicada aponta para a Obra que fica (ISBNs e tags).
    obra_por_gb |= {f.duplicada: obra_por_gb[f.fica] for f in fusoes}

    isbns = [
        {"isbn13": isbn, "obra_id": obra_por_gb[int(b.book_id)], "origem": OrigemIsbn.BASE}
        for b in books.itertuples(index=False)
        for isbn in isbn13_do_goodbooks(b.isbn, b.isbn13)
    ]
    # Os de uma carga anterior que o CSV não dá mais (o ISBN-13 arredondado de antes).
    conn.execute(
        delete(ObraIsbn).where(
            ObraIsbn.origem == OrigemIsbn.BASE, ObraIsbn.isbn13.not_in({i["isbn13"] for i in isbns})
        )
    )
    if isbns:
        # Um ISBN da Base que o `enriquecer-ol` pôs em outra Obra volta para a dela; um
        # gravado pela Resolução (origem `leitor`) fica onde está.
        stmt = insert(ObraIsbn)
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[ObraIsbn.isbn13],
                set_={"obra_id": stmt.excluded.obra_id, "origem": stmt.excluded.origem},
                where=ObraIsbn.origem == OrigemIsbn.OPEN_LIBRARY,
            ),
            isbns,
        )

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

    n_notas = _gravar_notas(pasta, set(obra_por_gb), fusoes)
    log.info("%d Notas da Base de coleitura em %s", n_notas, pasta / ARQUIVO_NOTAS)
    return ResumoCarga(obras=obras_da_base, isbns=len(isbns), tags=len(linhas_tag), notas=n_notas)


def _fundir_no_banco(conn: Connection, fusao: Fusao, fica: int) -> None:
    """Funde a Obra da duplicada, se existir de uma carga anterior, na que fica
    (`pipeline.fusao.fundir_obra`); o próximo `recalcular` refaz os Vizinhos."""
    duplicada = conn.execute(
        text("SELECT id FROM obra WHERE goodbooks_book_id = :g"), {"g": fusao.duplicada}
    ).scalar_one_or_none()
    if duplicada is not None:
        fundir_obra(conn, duplicada, fica)
    if fusao.titulo:
        # O título de exibição só difere do título quando há Edição em português (§6.2).
        conn.execute(
            text("UPDATE obra SET titulo_exibicao = titulo WHERE id = :f AND NOT tem_edicao_pt"),
            {"f": fica},
        )
