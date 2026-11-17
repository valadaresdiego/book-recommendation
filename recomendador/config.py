"""Configuração lida do `.env` (ver `.env.example`)."""

import uuid
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# A v1 tem um único Leitor (ADR 0005). Este id é criado pela migração inicial do esquema.
LEITOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Peso de cada Nota na pontuação de "Para você" (SPEC §8.5).
PESO_DA_NOTA: dict[int, float] = {5: 1.0, 4: 0.6, 3: 0.0, 2: -0.5, 1: -1.0}


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    database_url_test: str | None = None
    google_books_api_key: str = ""
    open_library_user_agent: str = "recomendador-pessoal/0.1"
    data_dir: Path = Path("./data")
    embedding_model: str = ""

    # SPEC §8.5: fase 2 usa só conteúdo (α = 1); a fase 3 calibra.
    alfa: float = 1.0
    max_sugestoes: int = 20
    min_notas_para_sugerir: int = 3


@lru_cache
def config() -> Config:
    return Config()  # type: ignore[call-arg]
