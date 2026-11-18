"""Liga as Obras aos Gêneros pelas tags de leitores (SPEC §6.3)."""

import logging
from dataclasses import dataclass

from sqlalchemy import Connection, text

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
    """Recalcula `obra_genero` inteira a partir de `obra_tag` e `genero_tag`."""
    conn.execute(text("DELETE FROM obra_genero"))
    conn.execute(_MAPEAR, {"minima": FORCA_MINIMA})

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
