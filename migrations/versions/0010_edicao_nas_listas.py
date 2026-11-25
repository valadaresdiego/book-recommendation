"""A Edição escolhida na busca nas listas Quero ler e Estou lendo (R8, SPEC §8.6, ADR 0010).

Um livro buscado pode ir direto para Quero ler; a Edição escolhida vai junto para Estou
lendo e para a Leitura do "Já li". Nula quando a Obra veio de "Para você" ou da página dela.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LISTAS = ("quero_ler", "estou_lendo")


def upgrade() -> None:
    for tabela in _LISTAS:
        op.add_column(
            tabela,
            sa.Column("edicao_id", sa.BigInteger, sa.ForeignKey("edicao.id", ondelete="SET NULL")),
        )


def downgrade() -> None:
    for tabela in _LISTAS:
        op.drop_column(tabela, "edicao_id")
