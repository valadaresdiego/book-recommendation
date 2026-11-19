"""Obras técnicas da Open Library (R14), da fase 6 (SPEC §8.8, ADR 0009).

- `obra.origem` ganha `open_library`: as Obras técnicas trazidas dos dumps.
- `obra.edicoes_ol`: o nº de Edições da work no dump, que ordena a Montagem da Estante.
- `obra.curada`: a Obra veio da lista curada (`catalogo/tecnicos_curados.yaml`).
- `execucao_modelo.tipo` ganha `tecnico`: Vizinhos de cada Obra entre as Obras técnicas.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE origem_obra ADD VALUE IF NOT EXISTS 'open_library'")
    op.execute("ALTER TYPE tipo_execucao ADD VALUE IF NOT EXISTS 'tecnico'")
    op.add_column("obra", sa.Column("edicoes_ol", sa.Integer))
    op.add_column(
        "obra", sa.Column("curada", sa.Boolean, server_default=sa.false(), nullable=False)
    )


def downgrade() -> None:
    # O Postgres não remove valores de um enum: só as colunas saem.
    op.drop_column("obra", "curada")
    op.drop_column("obra", "edicoes_ol")
