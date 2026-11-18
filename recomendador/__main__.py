"""CLI: `uv run python -m recomendador <comando>` (SPEC §6)."""

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    help="Recomendador de livros: comandos de banco e pipeline.", no_args_is_help=True
)
log = logging.getLogger("recomendador")

_PASTA_LOGS = Path(__file__).resolve().parents[1] / "logs"


@app.callback()
def _configurar_log() -> None:
    """Log no terminal e em logs/pipeline-AAAA-MM-DD.log (onde ficam as coberturas da carga)."""
    if log.handlers:
        return
    formato = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    _PASTA_LOGS.mkdir(exist_ok=True)
    arquivo = logging.FileHandler(
        _PASTA_LOGS / f"pipeline-{date.today():%Y-%m-%d}.log", "a", "utf-8"
    )
    terminal = logging.StreamHandler()
    for h in (arquivo, terminal):
        h.setFormatter(formato)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def _pendente(fase: str) -> None:
    typer.echo(f"Ainda não implementado ({fase}). Ver docs/SPEC.md.", err=True)
    raise typer.Exit(code=2)


def _engine():
    from recomendador.db.sessao import criar_engine

    return criar_engine()


@app.command("db-subir")
def db_subir() -> None:
    """Aplica as migrações e cria o Leitor e os Gêneros (de catalogo/generos.yaml)."""
    from recomendador.catalogo.generos import sincronizar_generos
    from recomendador.db.migracoes import aplicar_migracoes, garantir_leitor

    aplicar_migracoes()
    with _engine().begin() as conn:
        garantir_leitor(conn)
        n = sincronizar_generos(conn)
    log.info("Banco na última versão; %d Gêneros", n)


@app.command("carregar-base")
def carregar_base(
    fonte: Annotated[str, typer.Option(help="Base de coleitura a carregar.")] = "goodbooks10k",
) -> None:
    """Baixa (se faltar) e carrega o goodbooks-10k no Catálogo (SPEC §6.1)."""
    from recomendador.catalogo.fontes import goodbooks10k
    from recomendador.config import config
    from recomendador.pipeline.carga_goodbooks import carregar_base as carregar

    if fonte != "goodbooks10k":
        raise typer.BadParameter("só existe a fonte goodbooks10k na v1", param_hint="--fonte")
    pasta = config().data_dir / "raw"
    goodbooks10k.garantir_arquivos(pasta)
    with _engine().begin() as conn:
        r = carregar(conn, pasta)
    log.info("Carga concluída: %d Obras, %d ISBNs, %d tags, %d Notas", *vars(r).values())


@app.command("enriquecer-ol")
def enriquecer_ol(
    dumps: Annotated[Path, typer.Option(help="Pasta com os dumps works e editions.")] = Path(
        "data/ol"
    ),
    baixar: Annotated[bool, typer.Option(help="Baixa os dumps que faltam (~12 GB).")] = False,
) -> None:
    """Enriquece as Obras com os dumps da Open Library (SPEC §6.2)."""
    from recomendador.catalogo.fontes import open_library_dumps
    from recomendador.config import config
    from recomendador.pipeline.enriquecimento_ol import DumpAusente
    from recomendador.pipeline.enriquecimento_ol import enriquecer_ol as enriquecer

    if baixar:
        open_library_dumps.baixar(dumps, config().open_library_user_agent)
    try:
        with _engine().begin() as conn:
            enriquecer(conn, dumps)
    except DumpAusente as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e


@app.command("mapear-generos")
def mapear_generos() -> None:
    """Liga as Obras aos Gêneros via tags (SPEC §6.3). Relê catalogo/generos.yaml antes."""
    from recomendador.catalogo.generos import sincronizar_generos
    from recomendador.pipeline.generos import mapear_generos as mapear

    with _engine().begin() as conn:
        sincronizar_generos(conn)
        mapear(conn)


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
    """Rotina do logon (SPEC §10): migrações e `ultima_atualizacao`.

    Os passos 2 (embeddings das Obras do Leitor) e 3 (enriquecimento pela API da Open
    Library) entram nas fases 2 e 1, junto com o que eles atualizam.
    """
    from recomendador.db.migracoes import aplicar_migracoes, gravar_config

    aplicar_migracoes()
    with _engine().begin() as conn:
        gravar_config(conn, "ultima_atualizacao", datetime.now(UTC).isoformat())
    log.info("Atualização concluída")


if __name__ == "__main__":
    app()
