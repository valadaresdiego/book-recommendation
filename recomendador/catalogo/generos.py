"""Lista curada de Gêneros (SPEC §6.3), mantida em `generos.yaml` e espelhada no banco."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml
from sqlalchemy import Connection, delete, select, text
from sqlalchemy.dialects.postgresql import insert

from recomendador.db.modelos import Genero, GeneroTag

ARQUIVO_GENEROS = Path(__file__).with_name("generos.yaml")
ARQUIVO_CATEGORIAS = Path(__file__).with_name("categorias_google.yaml")
# As categorias do Google Books ficam em `obra_tag` com este prefixo e contagem 0.
PREFIXO_CATEGORIA = "google:"
# O Gênero das Obras técnicas (SPEC §8.8): define a aba "Tecnologia" de "Para você".
SLUG_TECNOLOGIA = "tecnologia"
# Uma Obra deste Gênero não é técnica, mesmo com tags de programação (*Ghost in the Wires*).
SLUG_BIOGRAFIAS = "biografias"


@dataclass(frozen=True)
class DefinicaoGenero:
    slug: str
    nome: str
    tags: tuple[str, ...]


def ler_generos(caminho: Path = ARQUIVO_GENEROS) -> list[DefinicaoGenero]:
    itens = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    generos = [
        DefinicaoGenero(slug=i["slug"], nome=i["nome"], tags=tuple(t.lower() for t in i["tags"]))
        for i in itens
    ]
    slugs = [g.slug for g in generos]
    if len(set(slugs)) != len(slugs):
        raise ValueError(f"{caminho}: slug de Gênero repetido")
    return generos


def sincronizar_generos(conn: Connection, caminho: Path = ARQUIVO_GENEROS) -> int:
    """Deixa `genero` e `genero_tag` iguais ao YAML. Gêneros fora do YAML são apagados."""
    generos = ler_generos(caminho)
    for g in generos:
        conn.execute(
            insert(Genero)
            .values(slug=g.slug, nome=g.nome)
            .on_conflict_do_update(index_elements=[Genero.slug], set_={"nome": g.nome})
        )
    conn.execute(delete(Genero).where(Genero.slug.not_in([g.slug for g in generos])))

    ids = dict(conn.execute(select(Genero.slug, Genero.id)).all())
    conn.execute(delete(GeneroTag))
    linhas = [{"genero_id": ids[g.slug], "tag": t} for g in generos for t in set(g.tags)]
    if linhas:
        conn.execute(insert(GeneroTag), linhas)
    return len(generos)


@dataclass(frozen=True)
class GeneroDoCatalogo:
    slug: str
    nome: str


def listar_generos(conn: Connection) -> list[GeneroDoCatalogo]:
    """Os Gêneros na ordem do `generos.yaml` (a ordem dos ids), para os chips da Montagem."""
    return [
        GeneroDoCatalogo(slug, nome)
        for slug, nome in conn.execute(select(Genero.slug, Genero.nome).order_by(Genero.id))
    ]


# --- Gênero das Obras do Leitor pelas categorias do Google Books (SPEC §6.3) ---


def _partes(categoria: str) -> tuple[str, ...]:
    return tuple(p.strip().lower() for p in categoria.split("/") if p.strip())


@cache
def ler_categorias(caminho: Path = ARQUIVO_CATEGORIAS) -> dict[str, str]:
    """Prefixo de categoria BISAC ("fiction / fantasy") → slug do Gênero."""
    itens = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    return {" / ".join(_partes(k)): v for k, v in itens.items()}


def generos_das_categorias(categorias: Iterable[str]) -> set[str]:
    """Os Gêneros das categorias do Google Books, pelo prefixo mais longo do mapa. Uma
    biografia sobre tecnologia (Steve Jobs) não é técnica, como nas tags (§6.3)."""
    mapa = ler_categorias()
    slugs: set[str] = set()
    for categoria in categorias:
        partes = _partes(categoria)
        for n in range(len(partes), 0, -1):
            if slug := mapa.get(" / ".join(partes[:n])):
                slugs.add(slug)
                break
    if SLUG_BIOGRAFIAS in slugs:
        slugs.discard(SLUG_TECNOLOGIA)
    return slugs


def gravar_generos_das_categorias(conn: Connection, obras: Sequence[int] | None = None) -> None:
    """Liga as Obras do Leitor (todas, ou só `obras`) aos Gêneros das categorias que têm,
    com força 1. As outras Obras ficam com os Gêneros das tags de leitores ou da carga
    técnica."""
    filtro = "" if obras is None else "AND t.obra_id = ANY(:obras)"
    por_obra: dict[int, list[str]] = {}
    for obra_id, tag in conn.execute(
        text(
            "SELECT t.obra_id, t.tag FROM obra_tag t JOIN obra o ON o.id = t.obra_id "
            f"WHERE o.origem = 'leitor' AND t.tag LIKE :prefixo {filtro}"
        ),
        {"prefixo": PREFIXO_CATEGORIA + "%", "obras": list(obras or [])},
    ):
        por_obra.setdefault(obra_id, []).append(tag.removeprefix(PREFIXO_CATEGORIA))
    linhas = [
        {"o": obra_id, "s": slug}
        for obra_id, categorias in por_obra.items()
        for slug in generos_das_categorias(categorias)
    ]
    if linhas:
        conn.execute(
            text(
                "INSERT INTO obra_genero (obra_id, genero_id, forca) "
                "SELECT :o, id, 1 FROM genero WHERE slug = :s "
                "ON CONFLICT (obra_id, genero_id) DO NOTHING"
            ),
            linhas,
        )


def registrar_categorias(conn: Connection, obra_id: int, categorias: Iterable[str]) -> None:
    """Grava as categorias da Edição do Google Books escolhida numa Obra do Leitor e liga a
    Obra aos Gêneros delas. Numa Obra da Base ou técnica, não faz nada: ela já tem Gênero."""
    tags = {PREFIXO_CATEGORIA + " / ".join(partes) for c in categorias if (partes := _partes(c))}
    origem = conn.execute(
        text("SELECT origem::text FROM obra WHERE id = :o"), {"o": obra_id}
    ).scalar_one()
    if not tags or origem != "leitor":
        return
    conn.execute(
        text(
            "INSERT INTO obra_tag (obra_id, tag, contagem) VALUES (:o, :t, 0) "
            "ON CONFLICT DO NOTHING"
        ),
        [{"o": obra_id, "t": t} for t in sorted(tags)],
    )
    gravar_generos_das_categorias(conn, [obra_id])
