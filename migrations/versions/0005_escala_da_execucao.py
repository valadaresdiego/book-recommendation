"""Escala de cada execução em `execucao_modelo.parametros` (ADR 0007).

A mistura do "Para você" (SPEC §8.5) divide a similaridade de cada execução pela escala
dela, a média das similaridades dos seus Vizinhos. `calcular-conteudo` e
`calcular-coleitura` passam a gravá-la; esta migração a preenche nas execuções que já
existiam, com a mesma média.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE execucao_modelo e
        SET parametros = coalesce(e.parametros, '{}'::jsonb)
                         || jsonb_build_object('escala', m.media)
        FROM (
            SELECT execucao_id, avg(similaridade)::float8 AS media
            FROM vizinho GROUP BY execucao_id
        ) m
        WHERE m.execucao_id = e.id
          AND m.media > 0
          AND NOT coalesce(e.parametros, '{}'::jsonb) ? 'escala'
        """
    )


def downgrade() -> None:
    op.execute("UPDATE execucao_modelo SET parametros = parametros - 'escala'")
