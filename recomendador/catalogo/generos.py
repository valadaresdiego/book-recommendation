"""Lista curada de Gêneros (SPEC §6.3), mantida em `generos.yaml` e espelhada no banco."""

from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import Connection, delete, select
from sqlalchemy.dialects.postgresql import insert

from recomendador.db.modelos import Genero, GeneroTag

ARQUIVO_GENEROS = Path(__file__).with_name("generos.yaml")


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
