"""Estou lendo (R13), da fase 5 (SPEC §8.7, ADR 0008).

A tabela é igual à `quero_ler`: uma Obra por Leitor, com a posição em "Para você" quando
veio de lá (O5).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "estou_lendo",
        sa.Column("leitor_id", UUID(as_uuid=True), sa.ForeignKey("leitor.id"), primary_key=True),
        sa.Column(
            "obra_id",
            sa.BigInteger,
            sa.ForeignKey("obra.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        ),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("posicao", sa.SmallInteger),
    )


def downgrade() -> None:
    op.drop_table("estou_lendo")
