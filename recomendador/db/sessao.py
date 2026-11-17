from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from recomendador.config import config


def criar_engine(url: str | None = None) -> Engine:
    return create_engine(url or config().database_url, pool_pre_ping=True)


_fabrica: sessionmaker[Session] | None = None


@contextmanager
def sessao() -> Iterator[Session]:
    """Uma unidade de trabalho: commit no fim, rollback em erro."""
    global _fabrica
    if _fabrica is None:
        _fabrica = sessionmaker(criar_engine(), expire_on_commit=False)
    with _fabrica() as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
