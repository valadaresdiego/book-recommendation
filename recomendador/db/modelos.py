"""Tabelas do domínio (SPEC §4). Entram na fase 0, junto com a migração correspondente."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
