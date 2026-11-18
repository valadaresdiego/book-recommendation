"""Tabelas do domínio (SPEC §4). As migrações em `migrations/versions/` criam exatamente isto.

`tests/test_esquema.py` compara estes modelos com o banco migrado: se mudar um, mude o outro.
"""

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    REAL,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Dimensão comum do bake-off de embeddings (SPEC §8.4.1).
DIMENSAO_EMBEDDING = 1024


class Base(DeclarativeBase):
    pass


class OrigemObra(enum.StrEnum):
    BASE = "base"  # veio da Base de coleitura
    LEITOR = "leitor"  # adicionada pelo Leitor


class OrigemIsbn(enum.StrEnum):
    BASE = "base"  # do goodbooks-10k (`carregar-base`)
    OPEN_LIBRARY = "open_library"  # de uma work do dump; o `enriquecer-ol` refaz a cada execução
    LEITOR = "leitor"  # de uma Edição gravada pela Resolução; nunca é apagado


class OrigemLeitura(enum.StrEnum):
    BUSCA = "busca"
    MONTAGEM = "montagem"
    SUGESTAO = "sugestao"
    MANUAL = "manual"
    CATALOGO = "catalogo"


class TipoExecucao(enum.StrEnum):
    CONTEUDO = "conteudo"
    COLEITURA = "coleitura"


def _enum(classe: type[enum.Enum], nome: str) -> Enum:
    return Enum(classe, name=nome, values_callable=lambda c: [m.value for m in c])


def _criado_em() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Leitor(Base):
    __tablename__ = "leitor"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    nome: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = _criado_em()


class ExecucaoModelo(Base):
    __tablename__ = "execucao_modelo"
    __table_args__ = (
        # No máximo uma execução ativa por tipo.
        Index(
            "execucao_modelo_uma_ativa_por_tipo",
            "tipo",
            unique=True,
            postgresql_where=text("ativa"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tipo: Mapped[TipoExecucao] = mapped_column(_enum(TipoExecucao, "tipo_execucao"))
    modelo: Mapped[str] = mapped_column(Text)
    parametros: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    metricas: Mapped[dict | None] = mapped_column(JSONB)
    ativa: Mapped[bool] = mapped_column(server_default=text("false"))
    criado_em: Mapped[datetime] = _criado_em()


class Obra(Base):
    __tablename__ = "obra"
    __table_args__ = (
        Index(
            "obra_titulo_trgm",
            "titulo",
            postgresql_using="gin",
            postgresql_ops={"titulo": "gin_trgm_ops"},
        ),
        Index(
            "obra_titulo_original_trgm",
            "titulo_original",
            postgresql_using="gin",
            postgresql_ops={"titulo_original": "gin_trgm_ops"},
        ),
        Index(
            "obra_titulo_exibicao_trgm",
            "titulo_exibicao",
            postgresql_using="gin",
            postgresql_ops={"titulo_exibicao": "gin_trgm_ops"},
        ),
        # Busca do R1 por títulos e autores, sem acento (migração 0003, SPEC §7.1).
        Index(
            "obra_texto_busca_trgm",
            # Expressão com rótulo, para a classe de operador ir em `postgresql_ops`.
            literal_column(
                "obra_texto_busca(titulo, titulo_original, titulo_exibicao, autores)"
            ).label("texto_busca"),
            postgresql_using="gin",
            postgresql_ops={"texto_busca": "gin_trgm_ops"},
        ),
        Index(
            "obra_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    titulo: Mapped[str] = mapped_column(Text)  # canônico, geralmente o original
    titulo_original: Mapped[str | None] = mapped_column(Text)
    titulo_exibicao: Mapped[str] = mapped_column(Text)  # de preferência o de uma Edição em pt
    autores: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    ano_original: Mapped[int | None] = mapped_column(Integer)
    descricao: Mapped[str | None] = mapped_column(Text)
    idioma_original: Mapped[str | None] = mapped_column(Text)
    capa_url: Mapped[str | None] = mapped_column(Text)
    origem: Mapped[OrigemObra] = mapped_column(_enum(OrigemObra, "origem_obra"))
    goodbooks_book_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    ol_work_key: Mapped[str | None] = mapped_column(Text, unique=True)
    popularidade: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(DIMENSAO_EMBEDDING))
    embedding_execucao_id: Mapped[int | None] = mapped_column(
        ForeignKey("execucao_modelo.id", ondelete="SET NULL")
    )
    enriquecida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criado_em: Mapped[datetime] = _criado_em()


class ObraIsbn(Base):
    """Todos os ISBNs conhecidos de cada Obra (de todas as suas Edições)."""

    __tablename__ = "obra_isbn"

    isbn13: Mapped[str] = mapped_column(String(13), primary_key=True)
    obra_id: Mapped[int] = mapped_column(ForeignKey("obra.id", ondelete="CASCADE"), index=True)
    origem: Mapped[OrigemIsbn] = mapped_column(_enum(OrigemIsbn, "origem_isbn"))


class Edicao(Base):
    __tablename__ = "edicao"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    obra_id: Mapped[int] = mapped_column(ForeignKey("obra.id", ondelete="CASCADE"), index=True)
    google_volume_id: Mapped[str | None] = mapped_column(Text, unique=True)
    ol_edition_key: Mapped[str | None] = mapped_column(Text)
    isbn13: Mapped[str | None] = mapped_column(String(13))
    titulo: Mapped[str] = mapped_column(Text)
    autores: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    editora: Mapped[str | None] = mapped_column(Text)
    ano: Mapped[int | None] = mapped_column(Integer)
    idioma: Mapped[str | None] = mapped_column(Text)
    capa_url: Mapped[str | None] = mapped_column(Text)


class Genero(Base):
    __tablename__ = "genero"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)


class GeneroTag(Base):
    """Mapeamento curado tag → Gênero (SPEC §6.3), sincronizado de `generos.yaml`."""

    __tablename__ = "genero_tag"

    genero_id: Mapped[int] = mapped_column(
        ForeignKey("genero.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(Text, primary_key=True)


class ObraGenero(Base):
    __tablename__ = "obra_genero"

    obra_id: Mapped[int] = mapped_column(
        ForeignKey("obra.id", ondelete="CASCADE"), primary_key=True
    )
    genero_id: Mapped[int] = mapped_column(
        ForeignKey("genero.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    forca: Mapped[float] = mapped_column(REAL)


class ObraTag(Base):
    """Top tags úteis de leitores (contagem > 0) e assuntos da Open Library (contagem = 0)."""

    __tablename__ = "obra_tag"

    obra_id: Mapped[int] = mapped_column(
        ForeignKey("obra.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(Text, primary_key=True)
    contagem: Mapped[int] = mapped_column(Integer)


class Leitura(Base):
    __tablename__ = "leitura"
    __table_args__ = (
        UniqueConstraint("leitor_id", "obra_id", name="leitura_uma_por_obra"),
        CheckConstraint("nota BETWEEN 1 AND 5", name="leitura_nota_de_1_a_5"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    leitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leitor.id"))
    obra_id: Mapped[int] = mapped_column(ForeignKey("obra.id"), index=True)
    edicao_id: Mapped[int | None] = mapped_column(ForeignKey("edicao.id", ondelete="SET NULL"))
    nota: Mapped[int | None] = mapped_column(SmallInteger)
    origem: Mapped[OrigemLeitura] = mapped_column(_enum(OrigemLeitura, "origem_leitura"))
    criado_em: Mapped[datetime] = _criado_em()
    atualizado_em: Mapped[datetime] = _criado_em()


class Vizinho(Base):
    __tablename__ = "vizinho"
    __table_args__ = (Index("vizinho_por_posicao", "execucao_id", "obra_id", "posicao"),)

    execucao_id: Mapped[int] = mapped_column(
        ForeignKey("execucao_modelo.id", ondelete="CASCADE"), primary_key=True
    )
    obra_id: Mapped[int] = mapped_column(
        ForeignKey("obra.id", ondelete="CASCADE"), primary_key=True
    )
    vizinho_id: Mapped[int] = mapped_column(
        ForeignKey("obra.id", ondelete="CASCADE"), primary_key=True
    )
    similaridade: Mapped[float] = mapped_column(REAL)
    posicao: Mapped[int] = mapped_column(SmallInteger)


class Evento(Base):
    __tablename__ = "evento"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    leitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leitor.id"))
    tipo: Mapped[str] = mapped_column(Text, index=True)
    obra_id: Mapped[int | None] = mapped_column(ForeignKey("obra.id", ondelete="SET NULL"))
    dados: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    criado_em: Mapped[datetime] = _criado_em()


class ConfigApp(Base):
    """Chave/valor do app, como `ultima_atualizacao` (SPEC §10)."""

    __tablename__ = "config_app"

    chave: Mapped[str] = mapped_column(Text, primary_key=True)
    valor: Mapped[dict] = mapped_column(JSONB)
    atualizado_em: Mapped[datetime] = _criado_em()
