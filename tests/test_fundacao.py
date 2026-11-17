from sqlalchemy import Connection, text
from typer.testing import CliRunner

from recomendador.__main__ import app


def test_extensoes_instaladas(conexao: Connection) -> None:
    nomes = set(conexao.execute(text("SELECT extname FROM pg_extension")).scalars())
    assert {"vector", "pg_trgm"} <= nomes


def test_pgvector_calcula_cosseno(conexao: Connection) -> None:
    distancia = conexao.execute(text("SELECT '[1,0]'::vector <=> '[0,1]'::vector")).scalar_one()
    assert distancia == 1.0


def test_cli_lista_comandos() -> None:
    resultado = CliRunner().invoke(app, ["--help"])
    assert resultado.exit_code == 0
    for comando in ["carregar-base", "calcular-conteudo", "avaliar", "atualizar"]:
        assert comando in resultado.output
