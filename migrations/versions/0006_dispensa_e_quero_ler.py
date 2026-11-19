"""Dispensa (R7), Quero ler (R8) e `obra.tem_edicao_pt` (R10), da fase 4 (SPEC §8.6).

`tem_edicao_pt` diz se a Obra tem alguma Edição em português, para o filtro de idioma de
"Para você". Quem a mantém é o `enriquecer-ol` (pelos dumps) e a Resolução (pelas Edições
do Leitor). Aqui ela é preenchida provisoriamente com o que o banco já sabe: um
`titulo_exibicao` diferente do `titulo` só vem de uma Edição em português (§6.2, §7.2), e
uma Edição gravada com `idioma = 'pt'` também conta. As Obras com Edição em português de
título igual ao canônico ficam de fora até o próximo `enriquecer-ol`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _colunas_da_lista() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table("dispensa", *_colunas_da_lista())
    op.create_table("quero_ler", *_colunas_da_lista(), sa.Column("posicao", sa.SmallInteger))
    op.add_column(
        "obra",
        sa.Column("tem_edicao_pt", sa.Boolean, server_default=sa.false(), nullable=False),
    )
    op.execute(
        """
        UPDATE obra o SET tem_edicao_pt = true
        WHERE o.titulo_exibicao <> o.titulo
           OR EXISTS (SELECT 1 FROM edicao e WHERE e.obra_id = o.id AND e.idioma = 'pt')
        """
    )


def downgrade() -> None:
    op.drop_column("obra", "tem_edicao_pt")
    op.drop_table("quero_ler")
    op.drop_table("dispensa")
