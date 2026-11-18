"""Esquema do domínio (SPEC §4) e o Leitor único da v1 (ADR 0005).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Copiado de recomendador.config.LEITOR_ID: migrações não importam o pacote.
LEITOR_ID = "00000000-0000-0000-0000-000000000001"

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "config_app",
        sa.Column("chave", sa.Text(), nullable=False),
        sa.Column("valor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("chave"),
    )
    op.create_table(
        "execucao_modelo",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.Enum("conteudo", "coleitura", name="tipo_execucao"), nullable=False),
        sa.Column("modelo", sa.Text(), nullable=False),
        sa.Column(
            "parametros",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("metricas", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ativa", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "execucao_modelo_uma_ativa_por_tipo",
        "execucao_modelo",
        ["tipo"],
        unique=True,
        postgresql_where=sa.text("ativa"),
    )
    op.create_table(
        "genero",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("nome", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "leitor",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("nome", sa.Text(), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "genero_tag",
        sa.Column("genero_id", sa.SmallInteger(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["genero_id"], ["genero.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("genero_id", "tag"),
    )
    op.create_table(
        "obra",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("titulo", sa.Text(), nullable=False),
        sa.Column("titulo_original", sa.Text(), nullable=True),
        sa.Column("titulo_exibicao", sa.Text(), nullable=False),
        sa.Column(
            "autores", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("ano_original", sa.Integer(), nullable=True),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("idioma_original", sa.Text(), nullable=True),
        sa.Column("capa_url", sa.Text(), nullable=True),
        sa.Column("origem", sa.Enum("base", "leitor", name="origem_obra"), nullable=False),
        sa.Column("goodbooks_book_id", sa.Integer(), nullable=True),
        sa.Column("ol_work_key", sa.Text(), nullable=True),
        sa.Column("popularidade", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.Column("embedding_execucao_id", sa.BigInteger(), nullable=True),
        sa.Column("enriquecida_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["embedding_execucao_id"], ["execucao_modelo.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goodbooks_book_id"),
        sa.UniqueConstraint("ol_work_key"),
    )
    op.create_index(
        "obra_embedding_hnsw",
        "obra",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "obra_titulo_exibicao_trgm",
        "obra",
        ["titulo_exibicao"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"titulo_exibicao": "gin_trgm_ops"},
    )
    op.create_index(
        "obra_titulo_original_trgm",
        "obra",
        ["titulo_original"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"titulo_original": "gin_trgm_ops"},
    )
    op.create_index(
        "obra_titulo_trgm",
        "obra",
        ["titulo"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"titulo": "gin_trgm_ops"},
    )
    op.create_table(
        "edicao",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("obra_id", sa.BigInteger(), nullable=False),
        sa.Column("google_volume_id", sa.Text(), nullable=True),
        sa.Column("ol_edition_key", sa.Text(), nullable=True),
        sa.Column("isbn13", sa.String(length=13), nullable=True),
        sa.Column("titulo", sa.Text(), nullable=False),
        sa.Column(
            "autores", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("editora", sa.Text(), nullable=True),
        sa.Column("ano", sa.Integer(), nullable=True),
        sa.Column("idioma", sa.Text(), nullable=True),
        sa.Column("capa_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["obra_id"], ["obra.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("google_volume_id"),
    )
    op.create_index(op.f("ix_edicao_obra_id"), "edicao", ["obra_id"], unique=False)
    op.create_table(
        "evento",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("leitor_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("obra_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "dados",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["leitor_id"],
            ["leitor.id"],
        ),
        sa.ForeignKeyConstraint(["obra_id"], ["obra.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evento_tipo"), "evento", ["tipo"], unique=False)
    op.create_table(
        "obra_genero",
        sa.Column("obra_id", sa.BigInteger(), nullable=False),
        sa.Column("genero_id", sa.SmallInteger(), nullable=False),
        sa.Column("forca", sa.REAL(), nullable=False),
        sa.ForeignKeyConstraint(["genero_id"], ["genero.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["obra_id"], ["obra.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("obra_id", "genero_id"),
    )
    op.create_index(op.f("ix_obra_genero_genero_id"), "obra_genero", ["genero_id"], unique=False)
    op.create_table(
        "obra_isbn",
        sa.Column("isbn13", sa.String(length=13), nullable=False),
        sa.Column("obra_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["obra_id"], ["obra.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("isbn13"),
    )
    op.create_index(op.f("ix_obra_isbn_obra_id"), "obra_isbn", ["obra_id"], unique=False)
    op.create_table(
        "obra_tag",
        sa.Column("obra_id", sa.BigInteger(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("contagem", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["obra_id"], ["obra.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("obra_id", "tag"),
    )
    op.create_table(
        "vizinho",
        sa.Column("execucao_id", sa.BigInteger(), nullable=False),
        sa.Column("obra_id", sa.BigInteger(), nullable=False),
        sa.Column("vizinho_id", sa.BigInteger(), nullable=False),
        sa.Column("similaridade", sa.REAL(), nullable=False),
        sa.Column("posicao", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(["execucao_id"], ["execucao_modelo.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["obra_id"], ["obra.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vizinho_id"], ["obra.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("execucao_id", "obra_id", "vizinho_id"),
    )
    op.create_index(
        "vizinho_por_posicao", "vizinho", ["execucao_id", "obra_id", "posicao"], unique=False
    )
    op.create_table(
        "leitura",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("leitor_id", sa.UUID(), nullable=False),
        sa.Column("obra_id", sa.BigInteger(), nullable=False),
        sa.Column("edicao_id", sa.BigInteger(), nullable=True),
        sa.Column("nota", sa.SmallInteger(), nullable=True),
        sa.Column(
            "origem",
            sa.Enum("busca", "montagem", "sugestao", "manual", "catalogo", name="origem_leitura"),
            nullable=False,
        ),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("nota BETWEEN 1 AND 5", name="leitura_nota_de_1_a_5"),
        sa.ForeignKeyConstraint(["edicao_id"], ["edicao.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["leitor_id"],
            ["leitor.id"],
        ),
        sa.ForeignKeyConstraint(
            ["obra_id"],
            ["obra.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("leitor_id", "obra_id", name="leitura_uma_por_obra"),
    )
    op.create_index(op.f("ix_leitura_obra_id"), "leitura", ["obra_id"], unique=False)
    op.execute(
        sa.text(
            "INSERT INTO leitor (id, nome) VALUES (CAST(:id AS uuid), 'Leitor') "
            "ON CONFLICT DO NOTHING"
        ).bindparams(id=LEITOR_ID)
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_leitura_obra_id"), table_name="leitura")
    op.drop_table("leitura")
    op.drop_index("vizinho_por_posicao", table_name="vizinho")
    op.drop_table("vizinho")
    op.drop_table("obra_tag")
    op.drop_index(op.f("ix_obra_isbn_obra_id"), table_name="obra_isbn")
    op.drop_table("obra_isbn")
    op.drop_index(op.f("ix_obra_genero_genero_id"), table_name="obra_genero")
    op.drop_table("obra_genero")
    op.drop_index(op.f("ix_evento_tipo"), table_name="evento")
    op.drop_table("evento")
    op.drop_index(op.f("ix_edicao_obra_id"), table_name="edicao")
    op.drop_table("edicao")
    op.drop_index(
        "obra_titulo_trgm",
        table_name="obra",
        postgresql_using="gin",
        postgresql_ops={"titulo": "gin_trgm_ops"},
    )
    op.drop_index(
        "obra_titulo_original_trgm",
        table_name="obra",
        postgresql_using="gin",
        postgresql_ops={"titulo_original": "gin_trgm_ops"},
    )
    op.drop_index(
        "obra_titulo_exibicao_trgm",
        table_name="obra",
        postgresql_using="gin",
        postgresql_ops={"titulo_exibicao": "gin_trgm_ops"},
    )
    op.drop_index(
        "obra_embedding_hnsw",
        table_name="obra",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("obra")
    op.drop_table("genero_tag")
    op.drop_table("leitor")
    op.drop_table("genero")
    op.drop_index(
        "execucao_modelo_uma_ativa_por_tipo",
        table_name="execucao_modelo",
        postgresql_where=sa.text("ativa"),
    )
    op.drop_table("execucao_modelo")
    op.drop_table("config_app")
    for tipo in ("origem_leitura", "origem_obra", "tipo_execucao"):
        op.execute(f"DROP TYPE IF EXISTS {tipo}")
