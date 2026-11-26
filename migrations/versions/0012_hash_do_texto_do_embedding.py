"""O hash do texto que virou o embedding de cada Obra (SPEC §7.3 e §10).

Uma Obra do Leitor cujo texto mudou depois do embedding (descrição e assuntos do
enriquecimento, Gêneros novos) fica pendente para o `atualizar`. Nulo quando o embedding
veio do arquivo de uma execução (`ativar`), que não guarda o texto.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("obra", sa.Column("embedding_texto_hash", sa.Text))


def downgrade() -> None:
    op.drop_column("obra", "embedding_texto_hash")
