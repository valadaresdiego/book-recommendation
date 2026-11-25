"""Tira do `titulo_exibicao` o idioma que as livrarias põem no título (SPEC §6.2).

"Insurgente (Em Portugues do Brasil)" vira "Insurgente". É a regra de
`catalogo.texto.titulo_sem_ruido`, que as cargas e a resolução passam a aplicar; aqui ela
corrige as Obras gravadas antes. Medido em 25/11/2026: 31 Obras da Base.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUIDO = r"(\s*\([^()]*(portugu|brasil)[^()]*\))+\s*$"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE obra SET titulo_exibicao = regexp_replace(titulo_exibicao, '{_RUIDO}', '', 'i')
        WHERE titulo_exibicao ~* '{_RUIDO}'
          AND regexp_replace(titulo_exibicao, '{_RUIDO}', '', 'i') <> ''
        """
    )


def downgrade() -> None:
    # O texto tirado não fica guardado: o `enriquecer-ol` o traria de volta, sem a regra.
    pass
