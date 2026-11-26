"""Leituras vindas da Importação do histórico do Goodreads (R9, SPEC §8.9, ADR 0011).

A origem própria deixa as Leituras importadas fora do O5 e do indicador da 1ª semana.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE origem_leitura ADD VALUE IF NOT EXISTS 'importacao'")


def downgrade() -> None:
    # O Postgres não remove valores de um enum. As Leituras importadas continuam com a origem.
    pass
