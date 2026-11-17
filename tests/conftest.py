"""Fixtures de banco: `recomendador_test` real, sem mocks (SPEC §12)."""

import subprocess
import sys
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, create_engine

from recomendador.config import config


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = config().database_url_test
    if not url:
        pytest.fail("DATABASE_URL_TEST não definido no .env")
    subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={url}", "upgrade", "head"], check=True
    )
    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def conexao(engine: Engine) -> Iterator[Connection]:
    """Cada teste roda numa transação revertida no fim."""
    with engine.connect() as conn:
        trans = conn.begin()
        yield conn
        trans.rollback()
