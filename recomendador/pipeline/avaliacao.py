"""`avaliar`: avaliação offline das execuções (SPEC §9).

Para cada leitor da amostra, monta uma Estante com as Notas de treino, pontua o Catálogo
como o "Para você" (§8.5, `recomendacao.pontuacao`) e compara as 20 primeiras Sugestões
com as Notas de teste. A semente fixa (42) torna tudo reprodutível.
"""

import json
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sqlalchemy import Connection, text

from recomendador.config import config
from recomendador.recomendacao.pontuacao import matriz_de_pesos, matriz_de_similaridade, pontuar

log = logging.getLogger(__name__)

N = 20
SEMENTE = 42
VARREDURA_BETA = (0.0, 0.25, 0.5, 1.0)  # peso da popularidade (ADR 0006, SPEC §9.4)
_LEITORES_POR_BLOCO = 500


@dataclass(frozen=True)
class Divisao:
    """Treino (Obra → Nota) e teste (Obras com Nota ≥ 4) de cada leitor da amostra."""

    leitores: list[int]
    treino: dict[int, dict[int, int]]
    teste: dict[int, set[int]]
    parametros: dict = field(default_factory=dict)


def dividir(
    notas: pd.DataFrame,
    n_leitores: int = 5000,
    min_notas: int = 20,
    frac_teste: float = 0.2,
    semente: int = SEMENTE,
) -> Divisao:
    """Sorteia `n_leitores` entre os que têm ≥ `min_notas` Notas (e alguma ≥ 4) e separa,
    de cada um, `frac_teste` das Notas ≥ 4 para o teste. `notas`: usuario_base, obra_id, nota.
    """
    rng = np.random.default_rng(semente)
    por_leitor = notas.groupby("usuario_base")
    contagem = por_leitor.size()
    com_boa = notas[notas.nota >= 4].groupby("usuario_base").size()
    elegiveis = sorted(set(contagem[contagem >= min_notas].index) & set(com_boa.index))
    n = min(n_leitores, len(elegiveis))
    leitores = sorted(int(u) for u in rng.choice(elegiveis, size=n, replace=False))

    treino: dict[int, dict[int, int]] = {}
    teste: dict[int, set[int]] = {}
    amostra = notas[notas.usuario_base.isin(leitores)].sort_values(["usuario_base", "obra_id"])
    for u, g in amostra.groupby("usuario_base"):
        boas = g.loc[g.nota >= 4, "obra_id"].to_numpy()
        quantas = max(1, round(frac_teste * len(boas)))
        sorteadas = {int(o) for o in rng.choice(boas, size=quantas, replace=False)}
        teste[int(u)] = sorteadas
        treino[int(u)] = {
            int(o): int(nota)
            for o, nota in zip(g.obra_id, g.nota, strict=True)
            if int(o) not in sorteadas
        }
    parametros = {
        "leitores": n,
        "min_notas": min_notas,
        "frac_teste": frac_teste,
        "semente": semente,
    }
    return Divisao(leitores, treino, teste, parametros)


def carregar_notas(conn: Connection, arquivo: Path) -> pd.DataFrame:
    """As Notas da Base de coleitura (`notas.parquet`) com o `obra_id` do Catálogo."""
    notas = pd.read_parquet(arquivo)
    mapa = dict(
        conn.execute(
            text("SELECT goodbooks_book_id, id FROM obra WHERE goodbooks_book_id IS NOT NULL")
        ).all()
    )
    notas["obra_id"] = notas["goodbooks_book_id"].map(mapa)
    return notas.dropna(subset=["obra_id"]).astype({"obra_id": "int64"})[
        ["usuario_base", "obra_id", "nota"]
    ]


# --- métricas ---


def ndcg(recomendadas: Sequence[int], relevantes: set[int], n: int = N) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, o in enumerate(recomendadas[:n]) if o in relevantes)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevantes), n)))
    return dcg / ideal if ideal else 0.0


def recall(recomendadas: Sequence[int], relevantes: set[int], n: int = N) -> float:
    if not relevantes:
        return 0.0
    return len(set(recomendadas[:n]) & relevantes) / len(relevantes)


def top_n(
    pontos: np.ndarray, treino: sparse.csr_matrix, popularidade: np.ndarray, n: int = N
) -> list[list[int]]:
    """As `n` colunas de maior pontuação (> 0) de cada linha, fora do treino; empates vão
    para a mais popular, como no "Para você"."""
    saida = []
    for i, linha in enumerate(pontos):
        p = linha.astype(np.float64)
        p[treino.indices[treino.indptr[i] : treino.indptr[i + 1]]] = -np.inf
        p[p <= 0] = -np.inf
        m = min(n, int(np.isfinite(p).sum()))
        if m == 0:
            saida.append([])
            continue
        limiar = np.partition(p, -m)[-m]
        cand = np.flatnonzero(p >= limiar)
        ordem = cand[np.lexsort((-popularidade[cand], -p[cand]))]
        saida.append([int(c) for c in ordem[:n]])
    return saida


# --- avaliação ---


@dataclass(frozen=True)
class ResultadoAvaliacao:
    metricas: dict[int, dict]
    popularidade: dict
    relatorio: Path


def avaliar(
    conn: Connection,
    execucoes: Sequence[int],
    divisao: Divisao,
    pasta_relatorios: Path,
    extras: dict[int, dict] | None = None,
    beta: float | None = None,
) -> ResultadoAvaliacao:
    """Avalia cada execução sozinha (conteúdo com α = 1, coleitura com α = 0) e a
    popularidade; grava `metricas` em cada execução e o relatório do dia.

    `extras` acrescenta métricas por execução (o teste entre idiomas do bake-off). As
    métricas principais usam o β da popularidade de `config` (ou `beta`); a varredura de
    `VARREDURA_BETA` vai junto, em `varredura_beta`, para a calibração do §9.4.
    """
    beta = config().beta_popularidade if beta is None else beta
    obras = conn.execute(
        text("SELECT id, popularidade FROM obra WHERE origem = 'base' ORDER BY id")
    ).all()
    indice = {o: i for i, (o, _) in enumerate(obras)}
    ids = np.array([o for o, _ in obras])
    popularidade = np.array([p for _, p in obras], dtype=np.float64)
    leitores = [u for u in divisao.leitores if divisao.teste[u]]
    estantes = [divisao.treino[u] for u in leitores]
    pesos = matriz_de_pesos(estantes, indice)
    treino = matriz_de_pesos([dict.fromkeys(e, 5) for e in estantes], indice)

    def medir(tops: list[list[int]]) -> dict:
        testes = [divisao.teste[u] for u in leitores]
        listas = [[int(ids[c]) for c in t] for t in tops]
        return {
            "ndcg@20": float(np.mean([ndcg(r, t) for r, t in zip(listas, testes, strict=True)])),
            "recall@20": float(
                np.mean([recall(r, t) for r, t in zip(listas, testes, strict=True)])
            ),
            "cobertura": len({c for t in tops for c in t}) / len(indice),
            "leitores": len(leitores),
        }

    pop = medir(top_n(np.tile(popularidade, (len(leitores), 1)), treino, popularidade))
    log.info("Popularidade: NDCG@20 %.4f", pop["ndcg@20"])

    resultado: dict[int, dict] = {}
    modelos: dict[int, str] = {}
    for execucao in execucoes:
        tipo, modelo = conn.execute(
            text("SELECT tipo::text, modelo FROM execucao_modelo WHERE id = :e"), {"e": execucao}
        ).one()
        modelos[execucao] = modelo
        triplas = conn.execute(
            text("SELECT obra_id, vizinho_id, similaridade FROM vizinho WHERE execucao_id = :e"),
            {"e": execucao},
        ).all()
        s = matriz_de_similaridade({tipo: triplas}, indice, alfa=1.0 if tipo == "conteudo" else 0.0)
        por_beta: dict[float, dict] = {}
        for b in sorted({*VARREDURA_BETA, beta}):
            tops: list[list[int]] = []
            for inicio in range(0, len(leitores), _LEITORES_POR_BLOCO):
                fim = inicio + _LEITORES_POR_BLOCO
                pontos = pontuar(pesos[inicio:fim], s, popularidade, b)
                tops += top_n(pontos, treino[inicio:fim], popularidade)
            por_beta[b] = medir(tops)
        m = por_beta[beta] | (extras or {}).get(execucao, {})
        m |= {
            "beta": beta,
            "varredura_beta": {
                str(b): {k: v[k] for k in ("ndcg@20", "recall@20", "cobertura")}
                for b, v in por_beta.items()
            },
            "baseline_popularidade_ndcg@20": pop["ndcg@20"],
            "divisao": divisao.parametros,
            "avaliado_em": date.today().isoformat(),
        }
        # Junta às métricas que já existiam (o teste entre idiomas do bake-off fica).
        resultado[execucao] = conn.execute(
            text(
                "UPDATE execucao_modelo "
                "SET metricas = coalesce(metricas, '{}'::jsonb) || CAST(:m AS jsonb) "
                "WHERE id = :e RETURNING metricas"
            ),
            {"m": json.dumps(m), "e": execucao},
        ).scalar_one()
        m = resultado[execucao]
        log.info("Execução %d (%s): NDCG@20 %.4f", execucao, modelo, m["ndcg@20"])

    relatorio = _escrever_relatorio(pasta_relatorios, resultado, modelos, pop, divisao)
    return ResultadoAvaliacao(resultado, pop, relatorio)


def _escrever_relatorio(
    pasta: Path, metricas: dict[int, dict], modelos: dict[int, str], pop: dict, divisao: Divisao
) -> Path:
    def br(x: float) -> str:
        return f"{x:.4f}".replace(".", ",")

    linhas = [
        f"# Avaliação offline — {date.today():%d/%m/%Y}",
        "",
        f"Divisão (SPEC §9.1): {json.dumps(divisao.parametros, ensure_ascii=False)}.",
        f"Leitores com teste: {pop['leitores']}.",
        "",
        f"Pontuação com β = {br(next(iter(metricas.values()))['beta']) if metricas else '—'} "
        "(peso da popularidade, ADR 0006).",
        "",
        "| Execução | Modelo | NDCG@20 | Recall@20 | Cobertura | Extras |",
        "|---|---|---|---|---|---|",
    ]
    base = (
        *("ndcg@20", "recall@20", "cobertura", "leitores", "divisao", "avaliado_em"),
        *("beta", "varredura_beta"),
    )
    for e, m in sorted(metricas.items(), key=lambda x: -x[1]["ndcg@20"]):
        extras = ", ".join(
            f"{k}: {v}" for k, v in m.items() if k not in base and not k.startswith("baseline")
        )
        linhas.append(
            f"| {e} | `{modelos[e]}` | {br(m['ndcg@20'])} | {br(m['recall@20'])} "
            f"| {br(m['cobertura'])} | {extras} |"
        )
    linhas.append(
        f"| — | Popularidade (baseline) | {br(pop['ndcg@20'])} | {br(pop['recall@20'])} "
        f"| {br(pop['cobertura'])} | |"
    )
    if metricas:
        betas = list(next(iter(metricas.values()))["varredura_beta"])
        linhas += [
            "",
            "## NDCG@20 (cobertura) por β",
            "",
            "| Execução | " + " | ".join(f"β = {b.replace('.', ',')}" for b in betas) + " |",
            "|---|" + "---|" * len(betas),
        ]
        for e, m in sorted(metricas.items()):
            v = m["varredura_beta"]
            celulas = [f"{br(v[b]['ndcg@20'])} ({br(v[b]['cobertura'])})" for b in betas]
            linhas.append(f"| {e} | " + " | ".join(celulas) + " |")
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"avaliacao-{date.today():%Y-%m-%d}.md"
    arquivo.write_bytes(("\n".join(linhas) + "\n").encode("utf-8"))
    return arquivo
