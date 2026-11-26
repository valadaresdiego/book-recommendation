"""Tira a origem `importacao` das Leituras: a Importação do Goodreads saiu do app (ADR 0011).

O Postgres não remove um valor de um enum, então o tipo `origem_leitura` é recriado sem ele.
Só a coluna `leitura.origem` usa o tipo, sem default nem índice. Uma Leitura com origem
`importacao` impede a migração, em vez de ter a origem trocada às cegas.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGENS = ("busca", "montagem", "sugestao", "manual", "catalogo")


def upgrade() -> None:
    importadas = op.get_bind().execute(
        sa.text("SELECT count(*) FROM leitura WHERE origem::text = 'importacao'")
    ).scalar_one()
    if importadas:
        raise RuntimeError(
            f"{importadas} Leituras têm origem 'importacao': troque a origem delas antes de "
            "migrar (por exemplo, para 'manual')"
        )
    valores = ", ".join(f"'{v}'" for v in _ORIGENS)
    op.execute("ALTER TYPE origem_leitura RENAME TO origem_leitura_antiga")
    op.execute(f"CREATE TYPE origem_leitura AS ENUM ({valores})")
    op.execute(
        "ALTER TABLE leitura ALTER COLUMN origem TYPE origem_leitura "
        "USING origem::text::origem_leitura"
    )
    op.execute("DROP TYPE origem_leitura_antiga")


def downgrade() -> None:
    op.execute("ALTER TYPE origem_leitura ADD VALUE IF NOT EXISTS 'importacao'")
