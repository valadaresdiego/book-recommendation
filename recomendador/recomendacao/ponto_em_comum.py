"""O Ponto em comum de cada item de "Parecidos com este" (R5a, SPEC §8.3).

A Similaridade de conteúdo vem do embedding, que não se explica sozinho. O Ponto em comum
mostra o que a Obra e o Vizinho compartilham nos metadados, nesta ordem (decisão do
Leitor, 26/11/2026):

1. um autor;
2. as tags de leitores em comum mais raras no Catálogo (até 2), entre as 15 de maior
   contagem de cada Obra, sem as genéricas;
3. o Gênero em comum mais forte na Obra, menos Tecnologia: os Parecidos de uma Obra técnica
   são todos de Tecnologia (§8.8), e "Também Tecnologia" não diria nada (decisão do
   Leitor, 26/11/2026).

Sem nada disso, não há Ponto em comum. Os assuntos da Open Library ficam de fora: vêm em
várias línguas e com ruído ("cheng gong fa", "new york times reviewed"). O texto é montado
só na UI.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text

from recomendador.catalogo.generos import SLUG_TECNOLOGIA
from recomendador.catalogo.tags import tag_util
from recomendador.catalogo.texto import normalizar

MAX_TAGS = 15  # as mesmas do texto do embedding (§8.2)
MAX_TEMAS = 2
# Tags que dizem quase nada sobre a Obra: descrevem a forma, o público ou a origem.
TAGS_GENERICAS = frozenset(
    {
        "fiction", "non-fiction", "nonfiction", "novels", "novel", "adult", "adult-fiction",
        "general-fiction", "literature", "series", "english", "american",
    }
)  # fmt: skip


def _generica(tag: str) -> bool:
    """Genérica ou da relação do leitor com o livro ("my-ebooks", "tbr"). A carga já tira
    estas (§6.1), mas um banco carregado antes do filtro atual ainda pode tê-las."""
    return tag.lower() in TAGS_GENERICAS or not tag_util(tag)


@dataclass(frozen=True)
class PontoEmComum:
    tipo: Literal["autor", "temas", "genero"]
    valores: tuple[str, ...]  # o autor; até 2 temas, do mais raro ao mais comum; o Gênero


@dataclass(frozen=True)
class Metadados:
    autores: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()  # de leitores, da maior contagem para a menor
    generos: tuple[str, ...] = ()  # nomes, da maior força para a menor


def ponto_em_comum(
    obra: Metadados, vizinho: Metadados, obras_por_tag: Mapping[str, int]
) -> PontoEmComum | None:
    """O que `obra` e `vizinho` compartilham. `obras_por_tag`: em quantas Obras do Catálogo
    cada tag aparece; a mais rara diz mais sobre o par."""
    autores_do_vizinho = {normalizar(a) for a in vizinho.autores}
    for autor in obra.autores:
        if normalizar(autor) in autores_do_vizinho:
            return PontoEmComum("autor", (autor,))
    do_vizinho = set(vizinho.tags[:MAX_TAGS])
    comuns = [t for t in obra.tags[:MAX_TAGS] if t in do_vizinho and not _generica(t)]
    if comuns:
        mais_raras = sorted(comuns, key=lambda t: obras_por_tag.get(t, 0))[:MAX_TEMAS]
        return PontoEmComum("temas", tuple(_tema(t) for t in mais_raras))
    generos_do_vizinho = set(vizinho.generos)
    for genero in obra.generos:
        if genero in generos_do_vizinho:
            return PontoEmComum("genero", (genero,))
    return None


def _tema(tag: str) -> str:
    """ "decision-making" vira "decision making", como no texto do embedding."""
    return " ".join(tag.replace("-", " ").lower().split())


_METADADOS = text(
    """
    SELECT o.id, o.autores,
           coalesce((SELECT array_agg(t.tag ORDER BY t.contagem DESC, t.tag)
                     FROM (SELECT tag, contagem FROM obra_tag
                           WHERE obra_id = o.id AND contagem > 0
                           ORDER BY contagem DESC, tag LIMIT :max_tags) t), '{}') AS tags,
           -- Sem Tecnologia, que não conta como Gênero em comum.
           coalesce((SELECT array_agg(g.nome ORDER BY og.forca DESC, g.nome)
                     FROM obra_genero og JOIN genero g ON g.id = og.genero_id
                     WHERE og.obra_id = o.id AND g.slug <> :tecnologia), '{}') AS generos
    FROM obra o
    WHERE o.id = ANY(:ids)
    """
)

_OBRAS_POR_TAG = text(
    "SELECT tag, count(*) AS obras FROM obra_tag "
    "WHERE contagem > 0 AND tag = ANY(:tags) GROUP BY tag"
)


def pontos_em_comum(
    conn: Connection, obra_id: int, vizinhos: Sequence[int]
) -> dict[int, PontoEmComum | None]:
    """O Ponto em comum de cada Vizinho de `obra_id`, por id."""
    if not vizinhos:
        return {}
    dados = {
        r.id: Metadados(tuple(r.autores), tuple(r.tags), tuple(r.generos))
        for r in conn.execute(
            _METADADOS,
            {"ids": [obra_id, *vizinhos], "max_tags": MAX_TAGS, "tecnologia": SLUG_TECNOLOGIA},
        )
    }
    obra = dados.get(obra_id, Metadados())
    candidatas = {t for v in vizinhos for t in dados.get(v, Metadados()).tags} & set(obra.tags)
    obras_por_tag = (
        dict(conn.execute(_OBRAS_POR_TAG, {"tags": sorted(candidatas)}).all()) if candidatas else {}
    )
    return {v: ponto_em_comum(obra, dados.get(v, Metadados()), obras_por_tag) for v in vizinhos}
