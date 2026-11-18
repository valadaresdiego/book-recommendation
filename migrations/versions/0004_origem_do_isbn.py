"""Origem de cada ISBN em `obra_isbn` (SPEC §4 e §6.2).

Sem a origem, o `enriquecer-ol` não conseguia apagar os ISBNs que trouxe de uma work
errada numa execução anterior: eles continuavam votando nela e resolvendo Edições para a
Obra errada (uma Edição de *Hamlet* caía em *Twelfth Night*). Com a coluna `origem`:

- `base`: veio do goodbooks-10k (`carregar-base`);
- `open_library`: veio de uma work do dump (`enriquecer-ol`, que apaga e refaz esses a
  cada execução);
- `leitor`: veio de uma Edição gravada pela Resolução; nunca é apagado.

A tabela não guardava de onde veio cada ISBN, então o preenchimento é aproximado: os ISBNs
de Obras do Leitor e os das Edições gravadas viram `leitor`, e o resto, `open_library`. O
`carregar-base` seguinte devolve aos ISBNs do goodbooks-10k a origem `base`; rode-o antes
do `enriquecer-ol`.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGEM = sa.Enum("base", "open_library", "leitor", name="origem_isbn")


def upgrade() -> None:
    _ORIGEM.create(op.get_bind())
    op.add_column("obra_isbn", sa.Column("origem", _ORIGEM, nullable=True))
    op.execute(
        """
        UPDATE obra_isbn i SET origem = CASE
            WHEN o.origem = 'leitor'
              OR EXISTS (SELECT 1 FROM edicao e WHERE e.isbn13 = i.isbn13) THEN 'leitor'
            ELSE 'open_library'
        END::origem_isbn
        FROM obra o WHERE o.id = i.obra_id
        """
    )
    op.alter_column("obra_isbn", "origem", nullable=False)


def downgrade() -> None:
    op.drop_column("obra_isbn", "origem")
    _ORIGEM.drop(op.get_bind())
