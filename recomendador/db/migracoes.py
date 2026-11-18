"""Migrações (Alembic) e os dados fixos que o app precisa no banco."""

import json
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Connection, text

from recomendador.config import LEITOR_ID

_RAIZ = Path(__file__).resolve().parents[2]


def aplicar_migracoes(url: str | None = None) -> None:
    """`alembic upgrade head`, de qualquer pasta. Sem `url`, usa DATABASE_URL."""
    cfg = AlembicConfig(str(_RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(_RAIZ / "migrations"))
    if url:
        cfg.attributes["url"] = url
    command.upgrade(cfg, "head")


def garantir_leitor(conn: Connection) -> None:
    """O Leitor único da v1 (ADR 0005). A migração já o cria; isto cobre um banco restaurado."""
    conn.execute(
        text("INSERT INTO leitor (id, nome) VALUES (:id, 'Leitor') ON CONFLICT DO NOTHING"),
        {"id": LEITOR_ID},
    )


def gravar_config(conn: Connection, chave: str, valor: object) -> None:
    conn.execute(
        text(
            "INSERT INTO config_app (chave, valor) VALUES (:c, CAST(:v AS jsonb)) "
            "ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor, atualizado_em = now()"
        ),
        {"c": chave, "v": json.dumps(valor)},
    )
