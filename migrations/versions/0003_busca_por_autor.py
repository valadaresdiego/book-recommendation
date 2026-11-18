"""Busca do Catálogo por título e autor, sem acento (SPEC §7.1).

A 0002 só indexou os títulos. A busca do R1 também procura em `autores` (text[]) e precisa
ignorar acentos ("fundacao" acha "Fundação"). Esta migração cria:

- `normalizar_busca(text)`: minúsculas e sem acento (`unaccent`), IMMUTABLE para poder
  ser indexada;
- `obra_texto_busca(...)`: títulos e autores de uma Obra num texto só, já normalizado;
- um índice GIN trigram sobre `obra_texto_busca`.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    # `unaccent(text)` é STABLE; com o dicionário explícito e qualificado, o resultado
    # não depende do search_path e a função pode ser IMMUTABLE.
    op.execute(
        """
        CREATE FUNCTION normalizar_busca(texto text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        RETURN lower(public.unaccent('public.unaccent'::regdictionary, texto))
        """
    )
    op.execute(
        """
        CREATE FUNCTION obra_texto_busca(
            titulo text, titulo_original text, titulo_exibicao text, autores text[]
        ) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        RETURN normalizar_busca(
            concat_ws(' ', titulo_exibicao, titulo, titulo_original,
                      array_to_string(autores, ' '))
        )
        """
    )
    op.execute(
        "CREATE INDEX obra_texto_busca_trgm ON obra USING gin "
        "(obra_texto_busca(titulo, titulo_original, titulo_exibicao, autores) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS obra_texto_busca_trgm")
    op.execute("DROP FUNCTION IF EXISTS obra_texto_busca(text, text, text, text[])")
    op.execute("DROP FUNCTION IF EXISTS normalizar_busca(text)")
    op.execute("DROP EXTENSION IF EXISTS unaccent")
