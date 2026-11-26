"""CLI: `uv run python -m recomendador <comando>` (SPEC §6)."""

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import text

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


@app.command("generos-do-leitor")
def generos_do_leitor() -> None:
    """Dá às Obras do Leitor de antes da regra os Gêneros das categorias do Google Books da
    Edição que já têm (SPEC §6.3). Só pede ao Google as que ainda não têm categorias."""
    from recomendador.catalogo.fontes.google_books import GoogleBooks
    from recomendador.config import config
    from recomendador.pipeline.generos import categorias_das_edicoes_do_leitor

    google = GoogleBooks(config().google_books_api_key, timeout=10)
    try:
        with _engine().begin() as conn:
            categorias_das_edicoes_do_leitor(conn, google)
    finally:
        google.fechar()


@app.command("carregar-tecnicas")
def carregar_tecnicas(
    dumps: Annotated[
        Path, typer.Option(help="Pasta com os dumps works, editions e authors.")
    ] = Path("data/ol"),
) -> None:
    """Carrega as Obras técnicas da Open Library (SPEC §8.8). Rode depois do `enriquecer-ol`
    e do `mapear-generos`, e em seguida o `calcular-tecnico`."""
    from recomendador.pipeline.enriquecimento_ol import DumpAusente
    from recomendador.pipeline.tecnicas import CuradaInvalida
    from recomendador.pipeline.tecnicas import carregar_tecnicas as carregar

    try:
        with _engine().begin() as conn:
            carregar(conn, dumps)
    except (DumpAusente, CuradaInvalida) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e


def _pasta_embeddings() -> Path:
    from recomendador.config import config

    return config().data_dir / "embeddings"


@app.command("calcular-conteudo")
def calcular_conteudo(
    modelo: Annotated[str, typer.Option(help="Modelo do Hugging Face (SPEC §8.4.1).")],
) -> None:
    """Gera embeddings e Vizinhos de conteúdo numa execução inativa (SPEC §8.2)."""
    from recomendador.pipeline.conteudo import calcular_conteudo as calcular
    from recomendador.recomendacao.embeddings import ModeloSentenceTransformers

    codificador = ModeloSentenceTransformers(modelo)
    with _engine().begin() as conn:
        r = calcular(conn, codificador, _pasta_embeddings())
    typer.echo(f"Execução {r.execucao_id} criada (inativa): {r.obras} Obras, {r.vizinhos} Vizinhos")


@app.command("calcular-tecnico")
def calcular_tecnico() -> None:
    """Embeddings das Obras técnicas que faltam e Vizinhos técnicos, numa execução que já
    entra ativa (SPEC §8.8). Usa o modelo da execução de conteúdo ativa."""
    from recomendador.pipeline.tecnico import calcular_tecnico as calcular
    from recomendador.recomendacao.interativo import carregar_codificador, modelo_de_conteudo_ativo

    with _engine().begin() as conn:
        modelo = modelo_de_conteudo_ativo(conn)
    if modelo is None:
        typer.echo("Não há execução de conteúdo ativa", err=True)
        raise typer.Exit(code=1)
    cod = carregar_codificador(modelo)
    with _engine().begin() as conn:
        r = calcular(conn, cod)
    typer.echo(
        f"Execução {r.execucao_id} (tecnico, ativa): {r.vizinhos} Vizinhos de {r.obras} Obras "
        f"entre {r.tecnicas} Obras técnicas; {r.embeddings_novos} embeddings novos"
    )


@app.command("bakeoff")
def bakeoff(
    modelos: Annotated[
        list[str] | None, typer.Option("--modelo", help="Finalista (repetível). Padrão: os 3.")
    ] = None,
    leitores: Annotated[int, typer.Option(help="Leitores da avaliação (SPEC §9.1).")] = 5000,
    refazer_pares: Annotated[
        bool, typer.Option(help="Escolhe de novo os 20 pares do teste entre idiomas.")
    ] = False,
) -> None:
    """Bake-off do modelo de embedding (SPEC §8.4): uma execução inativa por finalista,
    teste entre idiomas, tempo de uma Obra e avaliação offline. Não ativa nada."""
    import statistics
    import time

    import numpy as np

    from recomendador.catalogo.fontes.google_books import GoogleBooks
    from recomendador.config import config
    from recomendador.pipeline import bakeoff as b
    from recomendador.pipeline.avaliacao import avaliar as avaliar_execucoes
    from recomendador.pipeline.avaliacao import carregar_notas, dividir
    from recomendador.pipeline.conteudo import calcular_conteudo as calcular
    from recomendador.recomendacao.embeddings import FORMATOS, ModeloSentenceTransformers

    arquivo = Path("tests/dados/pares_pt_en.yaml")
    cache = config().data_dir / "bakeoff" / "pares_pt_en.json"
    google = GoogleBooks(config().google_books_api_key, timeout=10)
    try:
        with _engine().begin() as conn:
            if refazer_pares or not arquivo.exists():
                pares = b.escolher_pares(conn, google)
                b.gravar_pares(pares, arquivo, cache)
            else:
                pares = b.carregar_pares(arquivo, cache, google)
            obra_por_gb = dict(
                conn.execute(
                    text(
                        "SELECT goodbooks_book_id, id FROM obra WHERE goodbooks_book_id IS NOT NULL"
                    )
                ).all()
            )
    finally:
        google.fechar()
    log.info("Teste entre idiomas com %d pares", len(pares))

    extras: dict[int, dict] = {}
    for modelo in modelos or list(FORMATOS):
        cod = ModeloSentenceTransformers(modelo)
        with _engine().begin() as conn:
            r = calcular(conn, cod, _pasta_embeddings())
        with np.load(_pasta_embeddings() / f"conteudo-{r.execucao_id}.npz") as d:
            ids, e = d["ids"], d["embeddings"]
        idiomas = b.conferir_entre_idiomas(cod, pares, obra_por_gb, ids, e)
        tempos = []
        for p in pares[:10]:
            inicio = time.perf_counter()
            cod.codificar([p.texto()])
            tempos.append(1000 * (time.perf_counter() - inicio))
        extras[r.execucao_id] = {
            "entre_idiomas": idiomas.resumo(),
            "entre_idiomas_passou": idiomas.passou,
            "ms_uma_obra": round(statistics.median(tempos)),
            "s_catalogo": round(r.segundos_embedding),
        }
        log.info("%s: execução %d, %s", modelo, r.execucao_id, extras[r.execucao_id])
        cod.liberar()

    with _engine().begin() as conn:
        notas = carregar_notas(conn, config().data_dir / "raw" / "notas.parquet")
        resultado = avaliar_execucoes(
            conn, list(extras), dividir(notas, n_leitores=leitores), Path("reports"), extras
        )
    typer.echo(f"Relatório em {resultado.relatorio}")


def _arquivo_de_notas() -> Path:
    from recomendador.config import config

    return config().data_dir / "raw" / "notas.parquet"


@app.command("calcular-coleitura")
def calcular_coleitura(
    k: Annotated[int, typer.Option(help="Vizinhos guardados por Obra.")] = 20,
    lam: Annotated[
        float, typer.Option("--lambda", help="Encolhimento para pares com poucos coleitores.")
    ] = 10,
    min_coleitores: Annotated[
        int, typer.Option(help="Pares com menos coleitores que isto são zerados.")
    ] = 5,
) -> None:
    """Calcula os Vizinhos de Coleitura numa execução inativa (SPEC §8.1)."""
    from recomendador.pipeline.avaliacao import carregar_notas
    from recomendador.pipeline.coleitura import calcular_coleitura as calcular

    with _engine().begin() as conn:
        notas = carregar_notas(conn, _arquivo_de_notas())
        r = calcular(conn, notas, k, lam, min_coleitores)
    typer.echo(f"Execução {r.execucao_id} criada (inativa): {r.obras} Obras, {r.vizinhos} Vizinhos")


@app.command("avaliar")
def avaliar(
    execucoes: Annotated[list[int], typer.Argument(help="Ids das execuções a avaliar.")],
    leitores: Annotated[int, typer.Option(help="Leitores da amostra (SPEC §9.1).")] = 5000,
    varredura: Annotated[
        bool, typer.Option(help="Com uma execução de cada tipo, varre α × β × K × λ (§9.4).")
    ] = True,
) -> None:
    """Avaliação offline: Recall@20, NDCG@20 e cobertura (SPEC §9).

    Com exatamente uma execução de conteúdo e uma de Coleitura, avalia também as duas
    juntas e faz a varredura da calibração.
    """
    from recomendador.pipeline.avaliacao import avaliar as avaliar_execucoes
    from recomendador.pipeline.avaliacao import carregar_notas, dividir

    with _engine().begin() as conn:
        tipos = dict(
            conn.execute(
                text("SELECT id, tipo::text FROM execucao_modelo WHERE id = ANY(:e)"),
                {"e": list(execucoes)},
            ).all()
        )
        if faltam := set(execucoes) - set(tipos):
            raise typer.BadParameter(f"execuções inexistentes: {sorted(faltam)}")
        por_tipo = {t: [e for e in execucoes if tipos[e] == t] for t in ("conteudo", "coleitura")}
        combinar = (
            (por_tipo["conteudo"][0], por_tipo["coleitura"][0])
            if all(len(v) == 1 for v in por_tipo.values())
            else None
        )
        notas = carregar_notas(conn, _arquivo_de_notas())
        divisao = dividir(notas, n_leitores=leitores)
        r = avaliar_execucoes(
            conn,
            execucoes,
            divisao,
            Path("reports"),
            notas=notas,
            combinar=combinar,
            varredura=varredura,
        )
    typer.echo(f"Relatório em {r.relatorio}")


@app.command("ativar")
def ativar(
    execucao_id: Annotated[int, typer.Argument(help="Id da execução em execucao_modelo.")],
    forcar: Annotated[
        bool, typer.Option(help="Ativa mesmo sem avaliação ou com NDCG@20 menor que o da ativa.")
    ] = False,
) -> None:
    """Torna uma execução de modelo a ativa do seu tipo (SPEC §9.4)."""
    from recomendador.pipeline.execucoes import AtivacaoRecusada
    from recomendador.pipeline.execucoes import ativar as ativar_execucao

    try:
        with _engine().begin() as conn:
            ativar_execucao(conn, execucao_id, _pasta_embeddings(), forcar=forcar)
    except AtivacaoRecusada as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e


@app.command("recalcular")
def recalcular(
    modelo: Annotated[
        str | None, typer.Option(help="Modelo de conteúdo. Padrão: o da execução ativa.")
    ] = None,
    sem_conteudo: Annotated[
        bool, typer.Option(help="Não recalcula o conteúdo (o que leva mais tempo, na GPU).")
    ] = False,
    leitores: Annotated[int, typer.Option(help="Leitores da avaliação (SPEC §9.1).")] = 5000,
) -> None:
    """Recálculo completo (SPEC §6): `calcular-conteudo` + `calcular-coleitura` + `avaliar`
    + `ativar` das execuções novas que passarem no critério do §9.4.

    As execuções ativas são avaliadas de novo junto com as novas, com a mesma divisão.
    """
    from recomendador.pipeline.avaliacao import avaliar as avaliar_execucoes
    from recomendador.pipeline.avaliacao import carregar_notas, dividir
    from recomendador.pipeline.coleitura import calcular_coleitura as calcular_col
    from recomendador.pipeline.execucoes import AtivacaoRecusada
    from recomendador.pipeline.execucoes import ativar as ativar_execucao

    with _engine().begin() as conn:
        # A execução `tecnico` não tem avaliação offline (ADR 0009): o `ativar` do conteúdo
        # novo a refaz.
        ativas = dict(
            conn.execute(
                text(
                    "SELECT tipo::text, id FROM execucao_modelo "
                    "WHERE ativa AND tipo IN ('conteudo', 'coleitura')"
                )
            ).all()
        )
        if modelo is None and "conteudo" in ativas:
            modelo = conn.execute(
                text("SELECT modelo FROM execucao_modelo WHERE id = :e"),
                {"e": ativas["conteudo"]},
            ).scalar_one()
    novas: dict[str, int] = {}
    if not sem_conteudo:
        if modelo is None:
            raise typer.BadParameter("não há execução de conteúdo ativa", param_hint="--modelo")
        from recomendador.pipeline.conteudo import calcular_conteudo as calcular
        from recomendador.recomendacao.embeddings import ModeloSentenceTransformers

        cod = ModeloSentenceTransformers(modelo)
        with _engine().begin() as conn:
            novas["conteudo"] = calcular(conn, cod, _pasta_embeddings()).execucao_id
        cod.liberar()
    with _engine().begin() as conn:
        notas = carregar_notas(conn, _arquivo_de_notas())
        novas["coleitura"] = calcular_col(conn, notas).execucao_id

    conteudo = novas.get("conteudo", ativas.get("conteudo"))
    with _engine().begin() as conn:
        r = avaliar_execucoes(
            conn,
            sorted({*ativas.values(), *novas.values()}),
            dividir(notas, n_leitores=leitores),
            Path("reports"),
            notas=notas,
            combinar=(conteudo, novas["coleitura"]) if conteudo else None,
        )
    typer.echo(f"Relatório em {r.relatorio}")
    for tipo, execucao in novas.items():
        try:
            with _engine().begin() as conn:
                ativar_execucao(conn, execucao, _pasta_embeddings())
            typer.echo(f"Execução {execucao} ({tipo}) ativada")
        except AtivacaoRecusada as e:
            typer.echo(f"Execução {execucao} ({tipo}) não ativada: {e}")


@app.command("atualizar")
def atualizar() -> None:
    """Rotina de abertura do app (SPEC §10), em no máximo 10 min.

    1. Migrações. 2. Embeddings e Vizinhos de conteúdo das Obras do Leitor pendentes.
    3. Enriquece pela Open Library até 100 Obras do Leitor pendentes.
    4. Grava `ultima_atualizacao`.
    """
    import time

    from recomendador.catalogo.fontes.open_library import OpenLibrary
    from recomendador.config import config
    from recomendador.db.migracoes import aplicar_migracoes, gravar_config
    from recomendador.pipeline.enriquecimento_leitor import enriquecer_obras_do_leitor

    prazo = time.monotonic() + _PRAZO_DO_ATUALIZAR_S
    aplicar_migracoes()
    _embeddings_do_leitor(prazo)
    ol = OpenLibrary(config().open_library_user_agent)
    try:
        with _engine().begin() as conn:
            enriquecer_obras_do_leitor(conn, ol, prazo=prazo)
    finally:
        ol.fechar()
    with _engine().begin() as conn:
        gravar_config(conn, "ultima_atualizacao", datetime.now(UTC).isoformat())
    log.info("Atualização concluída")


_PRAZO_DO_ATUALIZAR_S = 10 * 60


def _embeddings_do_leitor(prazo: float) -> None:
    """Passo 2 do `atualizar`. O modelo só é carregado se houver Obra pendente."""
    from recomendador.pipeline.interativo import embeddings_pendentes, obras_pendentes
    from recomendador.recomendacao.interativo import (
        carregar_codificador,
        modelo_de_conteudo_ativo,
    )

    with _engine().begin() as conn:
        pendentes = obras_pendentes(conn)
        modelo = modelo_de_conteudo_ativo(conn)
    if not pendentes or modelo is None:
        return
    try:
        cod = carregar_codificador(modelo)
        with _engine().begin() as conn:
            embeddings_pendentes(conn, cod, prazo)
    except Exception:  # o app abre mesmo assim (SPEC §10)
        log.exception("Embeddings das Obras do Leitor ficaram para a próxima abertura")


if __name__ == "__main__":
    app()
