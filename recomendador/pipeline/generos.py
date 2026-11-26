"""Liga as Obras aos Gêneros pelas tags de leitores (SPEC §6.3)."""

import logging
from dataclasses import dataclass

from sqlalchemy import Connection, text

from recomendador.catalogo.fontes import FonteIndisponivel
from recomendador.catalogo.fontes.google_books import GoogleBooks
from recomendador.catalogo.generos import (
    PREFIXO_CATEGORIA,
    SLUG_BIOGRAFIAS,
    SLUG_TECNOLOGIA,
    gravar_generos_das_categorias,
    registrar_categorias,
)

log = logging.getLogger(__name__)

# Uma Obra pertence ao Gênero se as tags dele somam ao menos 5 % das tags úteis da Obra.
FORCA_MINIMA = 0.05
COBERTURA_ESPERADA = 0.90

_MAPEAR = text(
    """
    WITH total AS (
        SELECT obra_id, sum(contagem) AS soma
        FROM obra_tag WHERE contagem > 0
        GROUP BY obra_id
    ),
    por_genero AS (
        SELECT ot.obra_id, gt.genero_id, sum(ot.contagem) AS soma
        FROM obra_tag ot JOIN genero_tag gt ON gt.tag = ot.tag
        WHERE ot.contagem > 0
        GROUP BY ot.obra_id, gt.genero_id
    )
    INSERT INTO obra_genero (obra_id, genero_id, forca)
    SELECT g.obra_id, g.genero_id, g.soma::double precision / t.soma
    FROM por_genero g JOIN total t USING (obra_id)
    WHERE g.soma::double precision / t.soma >= :minima
    ON CONFLICT DO NOTHING
    """
)

_APAGAR = text(
    """
    DELETE FROM obra_genero og
    WHERE NOT EXISTS (
        SELECT 1 FROM obra o, genero g
        WHERE o.id = og.obra_id AND g.id = og.genero_id
          AND o.origem <> 'base' AND g.slug = :tecnologia
    )
    """
)

_SEM_BIOGRAFIAS = text(
    """
    DELETE FROM obra_genero og
    USING genero t, obra_genero ob, genero b
    WHERE t.id = og.genero_id AND t.slug = :tecnologia
      AND ob.obra_id = og.obra_id AND b.id = ob.genero_id AND b.slug = :biografias
    """
)


@dataclass(frozen=True)
class ResumoGeneros:
    obras: int
    obras_com_genero: int
    por_genero: dict[str, int]

    @property
    def cobertura(self) -> float:
        return self.obras_com_genero / self.obras if self.obras else 0.0


def mapear_generos(conn: Connection) -> ResumoGeneros:
    """Recalcula `obra_genero` a partir de `obra_tag` e `genero_tag`.

    A Tecnologia das Obras que não são da Base fica: o `carregar-tecnicas` a grava com
    força 1 pelos assuntos da Open Library, que têm contagem 0 e não a refariam (§8.8).
    As Obras do Leitor ganham os Gêneros das categorias do Google Books, com força 1.
    Uma Obra de Biografias e memórias sai de Tecnologia (§6.3).
    """
    conn.execute(_APAGAR, {"tecnologia": SLUG_TECNOLOGIA})
    conn.execute(_MAPEAR, {"minima": FORCA_MINIMA})
    gravar_generos_das_categorias(conn)
    conn.execute(_SEM_BIOGRAFIAS, {"tecnologia": SLUG_TECNOLOGIA, "biografias": SLUG_BIOGRAFIAS})

    obras = conn.execute(text("SELECT count(*) FROM obra")).scalar_one()
    com_genero = conn.execute(text("SELECT count(DISTINCT obra_id) FROM obra_genero")).scalar_one()
    por_genero = dict(
        conn.execute(
            text(
                "SELECT g.nome, count(og.obra_id) FROM genero g "
                "LEFT JOIN obra_genero og ON og.genero_id = g.id "
                "GROUP BY g.nome ORDER BY count(og.obra_id) DESC"
            )
        ).all()
    )
    resumo = ResumoGeneros(obras=obras, obras_com_genero=com_genero, por_genero=por_genero)

    log.info(
        "Obras com algum Gênero: %d de %d (%.1f %%)", com_genero, obras, 100 * resumo.cobertura
    )
    for nome, n in por_genero.items():
        log.info("  %-25s %6d", nome, n)
    if resumo.cobertura < COBERTURA_ESPERADA:
        log.warning(
            "Cobertura de Gêneros abaixo de %.0f %%: revise catalogo/generos.yaml",
            100 * COBERTURA_ESPERADA,
        )
    return resumo


def categorias_das_edicoes_do_leitor(conn: Connection, google: GoogleBooks) -> int:
    """Busca no Google Books as categorias das Edições já gravadas das Obras do Leitor que
    ainda não têm nenhuma (as de antes desta regra) e liga as Obras aos Gêneros delas.

    Devolve quantas Obras ganharam categorias. Para se o Google Books cair no meio.
    """
    pendentes = conn.execute(
        text(
            """
            SELECT DISTINCT ON (o.id) o.id, e.google_volume_id
            FROM obra o JOIN edicao e ON e.obra_id = o.id
            WHERE o.origem = 'leitor' AND e.google_volume_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM obra_tag t
                              WHERE t.obra_id = o.id AND t.tag LIKE :prefixo)
            ORDER BY o.id, e.id DESC
            """
        ),
        {"prefixo": PREFIXO_CATEGORIA + "%"},
    ).all()
    com_categorias = 0
    for obra_id, volume_id in pendentes:
        try:
            volume = google.volume(volume_id)
        except FonteIndisponivel as e:
            log.warning("Google Books indisponível; as outras Obras ficam para depois: %s", e)
            break
        if volume is not None and volume.categorias:
            registrar_categorias(conn, obra_id, volume.categorias)
            com_categorias += 1
    log.info(
        "Obras do Leitor com categorias do Google Books: %d de %d", com_categorias, len(pendentes)
    )
    return com_categorias
