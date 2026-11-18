"""Alembic: a URL vem de `-x url=...`, de `config.attributes["url"]` (chamada pelo pacote)
ou de DATABASE_URL no .env."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from recomendador.config import config as app_config
from recomendador.db.modelos import Base

target_metadata = Base.metadata


def _url() -> str:
    return (
        context.get_x_argument(as_dictionary=True).get("url")
        or context.config.attributes.get("url")
        or app_config().database_url
    )


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = engine_from_config(
        {"sqlalchemy.url": _url()}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
