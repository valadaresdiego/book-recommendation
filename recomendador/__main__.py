"""CLI: `uv run python -m recomendador <comando>` (SPEC §6)."""

import subprocess
import sys

import typer

app = typer.Typer(
    help="Recomendador de livros: comandos de banco e pipeline.", no_args_is_help=True
)


def _pendente(fase: str) -> None:
    typer.echo(f"Ainda não implementado ({fase}). Ver docs/SPEC.md.", err=True)
    raise typer.Exit(code=2)


@app.command("db-subir")
def db_subir() -> None:
    """Aplica as migrações pendentes (alembic upgrade head)."""
    raise typer.Exit(subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"]))


@app.command("carregar-base")
def carregar_base() -> None:
    """Carrega o goodbooks-10k no Catálogo (SPEC §6.1)."""
    _pendente("fase 0")


@app.command("enriquecer-ol")
def enriquecer_ol() -> None:
    """Enriquece as Obras com os dumps da Open Library (SPEC §6.2)."""
    _pendente("fase 0")


@app.command("mapear-generos")
def mapear_generos() -> None:
    """Liga as Obras aos Gêneros via tags (SPEC §6.3)."""
    _pendente("fase 0")


@app.command("calcular-conteudo")
def calcular_conteudo() -> None:
    """Gera embeddings e Vizinhos de conteúdo numa execução inativa (SPEC §8.2)."""
    _pendente("fase 2")


@app.command("calcular-coleitura")
def calcular_coleitura() -> None:
    """Calcula os Vizinhos de Coleitura numa execução inativa (SPEC §8.1)."""
    _pendente("fase 3")


@app.command("avaliar")
def avaliar() -> None:
    """Avaliação offline: Recall@20, NDCG@20 e cobertura (SPEC §9)."""
    _pendente("fase 2")


@app.command("ativar")
def ativar() -> None:
    """Torna uma execução de modelo a ativa do seu tipo."""
    _pendente("fase 2")


@app.command("recalcular")
def recalcular() -> None:
    """Recálculo completo, com avaliação e ativação condicional."""
    _pendente("fase 3")


@app.command("atualizar")
def atualizar() -> None:
    """Rotina do logon (SPEC §10). Por enquanto, só aplica as migrações."""
    raise typer.Exit(subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"]))


if __name__ == "__main__":
    app()
