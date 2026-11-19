"""`avaliar`: avaliação offline das execuções (SPEC §9).

Para cada leitor da amostra, monta uma Estante com as Notas de treino, pontua o Catálogo
como o "Para você" (§8.5, `recomendacao.pontuacao`) e compara as 20 primeiras Sugestões
com as Notas de teste. A semente fixa (42) torna tudo reprodutível.

A Coleitura avaliada nunca é a gravada em `vizinho`: ela é recalculada, com os parâmetros
da execução, só sobre as Notas de treino (§9.1). Senão as Notas de teste vazariam para os
Vizinhos. O conteúdo não usa Notas e é lido do banco.
"""

import csv
import itertools
import json
import logging
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sqlalchemy import Connection, text

from recomendador.config import PESO_DA_NOTA, config
from recomendador.pipeline.coleitura import MIN_COLEITORES, vizinhos_de_coleitura
from recomendador.recomendacao.pontuacao import (
    escala,
    matriz_de_pesos,
    matriz_de_similaridade,
    pontuar,
)

log = logging.getLogger(__name__)

N = 20
SEMENTE = 42
_LEITORES_POR_BLOCO = 500

# Calibração (SPEC §9.4). K e λ variam só a Coleitura: ela é recalculada sobre o treino,
# enquanto o conteúdo usa os Vizinhos gravados da execução.
VARREDURA_ALFA = (0.0, 0.25, 0.5, 0.75, 1.0)
VARREDURA_BETA = (0.0, 0.25, 0.5, 1.0)  # peso da popularidade (ADR 0006)
VARREDURA_K = (20, 50, 100)
VARREDURA_LAMBDA = (10, 50, 100)
TABELAS_DE_PESO: dict[str, Mapping[int, float]] = {
    "prd": PESO_DA_NOTA,
    "simetrica": {5: 1.0, 4: 0.5, 3: 0.0, 2: -0.5, 1: -1.0},
}
_METRICAS = ("ndcg@20", "recall@20", "cobertura")


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


def notas_de_treino(notas: pd.DataFrame, divisao: Divisao) -> pd.DataFrame:
    """Todas as Notas menos as de teste da `divisao`: a base da Coleitura avaliada (§9.1)."""
    teste = pd.DataFrame(
        [(u, o) for u, obras in divisao.teste.items() for o in obras],
        columns=["usuario_base", "obra_id"],
    ).astype({"usuario_base": notas["usuario_base"].dtype, "obra_id": notas["obra_id"].dtype})
    marcadas = notas[["usuario_base", "obra_id"]].merge(
        teste.assign(_teste=True), how="left", on=["usuario_base", "obra_id"]
    )
    return notas[marcadas["_teste"].isna().to_numpy()]


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
    p = np.array(pontos, dtype=np.float64)
    linhas = np.repeat(np.arange(treino.shape[0]), np.diff(treino.indptr))
    p[linhas, treino.indices] = -np.inf
    p[p <= 0] = -np.inf
    m = min(n, p.shape[1])
    limiares = np.partition(p, -m, axis=1)[:, -m]
    saida = []
    for linha, limiar in zip(p, limiares, strict=True):
        cand = np.flatnonzero(linha >= limiar if np.isfinite(limiar) else np.isfinite(linha))
        ordem = cand[np.lexsort((-popularidade[cand], -linha[cand]))]
        saida.append([int(c) for c in ordem[:n]])
    return saida


# --- a amostra e a Coleitura do treino ---


class _Amostra:
    """O que não muda entre as configurações avaliadas: o Catálogo da Base, os leitores
    com teste, as Estantes de treino e os pesos delas por tabela."""

    def __init__(self, conn: Connection, divisao: Divisao):
        obras = conn.execute(
            text("SELECT id, popularidade FROM obra WHERE origem = 'base' ORDER BY id")
        ).all()
        self.indice = {o: i for i, (o, _) in enumerate(obras)}
        self.ids = np.array([o for o, _ in obras])
        self.popularidade = np.array([p for _, p in obras], dtype=np.float64)
        self.leitores = [u for u in divisao.leitores if divisao.teste[u]]
        self.testes = [divisao.teste[u] for u in self.leitores]
        self.estantes = [divisao.treino[u] for u in self.leitores]
        self.treino = matriz_de_pesos([dict.fromkeys(e, 5) for e in self.estantes], self.indice)
        self._pesos: dict[str, sparse.csr_matrix] = {}

    def pesos(self, tabela: str) -> sparse.csr_matrix:
        if tabela not in self._pesos:
            self._pesos[tabela] = matriz_de_pesos(
                self.estantes, self.indice, TABELAS_DE_PESO[tabela]
            )
        return self._pesos[tabela]

    def similaridade(self, vizinhos: Mapping[str, list[tuple]], alfa: float):
        """S misturada por α, com a escala de cada tipo tirada dos próprios Vizinhos
        (a mesma média que `calcular-*` grava em `parametros.escala`, ADR 0007)."""
        escalas = {t: escala(x[2] for x in v) for t, v in vizinhos.items()}
        return matriz_de_similaridade(vizinhos, self.indice, alfa, escalas)

    def medir(self, tops: list[list[int]]) -> dict:
        listas = [[int(self.ids[c]) for c in t] for t in tops]
        pares = list(zip(listas, self.testes, strict=True))
        return {
            "ndcg@20": float(np.mean([ndcg(r, t) for r, t in pares])),
            "recall@20": float(np.mean([recall(r, t) for r, t in pares])),
            "cobertura": len({c for t in tops for c in t}) / len(self.indice),
            "leitores": len(self.leitores),
        }

    def popular(self) -> dict:
        """O baseline: as mais populares fora do treino."""
        tops: list[list[int]] = []
        for inicio in range(0, len(self.leitores), _LEITORES_POR_BLOCO):
            treino = self.treino[inicio : inicio + _LEITORES_POR_BLOCO]
            pontos = np.tile(self.popularidade, (treino.shape[0], 1))
            tops += top_n(pontos, treino, self.popularidade)
        return self.medir(tops)

    def avaliar(
        self, s: sparse.csr_matrix, betas: Iterable[float], tabela: str = "prd"
    ) -> dict[float, dict]:
        """As métricas da pontuação com a similaridade `s`, para cada β."""
        betas = list(betas)
        tops: dict[float, list[list[int]]] = {b: [] for b in betas}
        pesos = self.pesos(tabela)
        for inicio in range(0, len(self.leitores), _LEITORES_POR_BLOCO):
            fim = inicio + _LEITORES_POR_BLOCO
            for b in betas:
                pontos = pontuar(pesos[inicio:fim], s, self.popularidade, b)
                tops[b] += top_n(pontos, self.treino[inicio:fim], self.popularidade)
        return {b: self.medir(t) for b, t in tops.items()}


class _ColeituraNoTreino:
    """Os Vizinhos de Coleitura calculados só com as Notas de treino, guardados por
    (λ, mínimo de coleitores) com o maior K da varredura e cortados no K pedido."""

    def __init__(self, notas: pd.DataFrame, indice: Mapping[int, int]):
        self._notas = notas
        self._indice = indice
        self._ids = np.array(list(indice), dtype=np.int64)
        self._calculados: dict[tuple[float, int], tuple[np.ndarray, ...]] = {}

    def triplas(self, k: int, lam: float, min_coleitores: int) -> list[tuple]:
        chave = (lam, min_coleitores)
        if chave not in self._calculados or self._calculados[chave][4] < k:
            maior = max(k, *VARREDURA_K)
            log.info("Coleitura do treino com λ = %s (K até %d)", lam, maior)
            vizinhos = vizinhos_de_coleitura(self._notas, self._indice, maior, lam, min_coleitores)
            obra, vizinho, sim, posicao = [], [], [], []
            for i, lista in enumerate(vizinhos):
                for p, (j, s) in enumerate(lista, 1):
                    obra.append(i)
                    vizinho.append(j)
                    sim.append(s)
                    posicao.append(p)
            self._calculados[chave] = (
                self._ids[np.array(obra, dtype=np.int64)],
                self._ids[np.array(vizinho, dtype=np.int64)],
                np.array(sim),
                np.array(posicao),
                maior,
            )
        obra, vizinho, sim, posicao, _ = self._calculados[chave]
        dentro = posicao <= k
        return list(
            zip(obra[dentro].tolist(), vizinho[dentro].tolist(), sim[dentro].tolist(), strict=True)
        )


# --- avaliação ---


@dataclass(frozen=True)
class ResultadoAvaliacao:
    metricas: dict[int, dict]
    popularidade: dict
    relatorio: Path
    combinada: dict | None = None
    varredura: list[dict] = field(default_factory=list)


def avaliar(
    conn: Connection,
    execucoes: Sequence[int],
    divisao: Divisao,
    pasta_relatorios: Path,
    extras: dict[int, dict] | None = None,
    beta: float | None = None,
    *,
    notas: pd.DataFrame | None = None,
    combinar: tuple[int, int] | None = None,
    varredura: bool = True,
) -> ResultadoAvaliacao:
    """Avalia cada execução sozinha (conteúdo com α = 1, Coleitura com α = 0) e a
    popularidade; grava `metricas` em cada execução e o relatório do dia.

    - `notas` (todas as da Base) é obrigatório para avaliar Coleitura: ela é recalculada
      sobre `notas_de_treino`.
    - `combinar=(conteudo, coleitura)` avalia também as duas juntas, com o α de `config`
      (em `metricas.combinada` das duas) e, com `varredura`, a calibração do §9.4.
    - `extras` acrescenta métricas por execução (o teste entre idiomas do bake-off).
    - As métricas principais usam o β de `config` (ou `beta`) e a tabela de pesos do PRD.
    """
    cfg = config()
    beta = cfg.beta_popularidade if beta is None else beta
    amostra = _Amostra(conn, divisao)
    pop = amostra.popular()
    log.info("Popularidade: NDCG@20 %.4f", pop["ndcg@20"])
    coleitura = (
        _ColeituraNoTreino(notas_de_treino(notas, divisao), amostra.indice)
        if notas is not None
        else None
    )

    def vizinhos(execucao: int) -> tuple[str, dict, Iterable[tuple]]:
        tipo, parametros = conn.execute(
            text("SELECT tipo::text, parametros FROM execucao_modelo WHERE id = :e"),
            {"e": execucao},
        ).one()
        parametros = parametros or {}
        if tipo == "conteudo":
            triplas = conn.execute(
                text(
                    "SELECT obra_id, vizinho_id, similaridade FROM vizinho WHERE execucao_id = :e"
                ),
                {"e": execucao},
            ).all()
            return tipo, parametros, triplas
        if coleitura is None:
            raise ValueError("avaliar uma execução de Coleitura exige as `notas`")
        return tipo, parametros, coleitura.triplas(*_parametros_da_coleitura(parametros))

    resultado: dict[int, dict] = {}
    modelos: dict[int, str] = {}
    triplas_por_execucao: dict[int, list] = {}
    for execucao in execucoes:
        tipo, _, triplas = vizinhos(execucao)
        triplas_por_execucao[execucao] = triplas = list(triplas)
        modelos[execucao] = conn.execute(
            text("SELECT modelo FROM execucao_modelo WHERE id = :e"), {"e": execucao}
        ).scalar_one()
        s = amostra.similaridade({tipo: triplas}, alfa=1.0 if tipo == "conteudo" else 0.0)
        por_beta = amostra.avaliar(s, sorted({*VARREDURA_BETA, beta}))
        m = por_beta[beta] | (extras or {}).get(execucao, {})
        m |= {
            "beta": beta,
            "varredura_beta": {
                str(b): {k: v[k] for k in _METRICAS} for b, v in sorted(por_beta.items())
            },
            "baseline_popularidade_ndcg@20": pop["ndcg@20"],
            "divisao": divisao.parametros,
            "avaliado_em": date.today().isoformat(),
        }
        resultado[execucao] = _gravar(conn, execucao, m)
        log.info("Execução %d (%s): NDCG@20 %.4f", execucao, modelos[execucao], m["ndcg@20"])

    combinada = None
    linhas: list[dict] = []
    if combinar:
        c, col = combinar
        tipos = dict(
            conn.execute(
                text("SELECT id, tipo::text FROM execucao_modelo WHERE id IN (:c, :l)"),
                {"c": c, "l": col},
            ).all()
        )
        if tipos.get(c) != "conteudo" or tipos.get(col) != "coleitura":
            raise ValueError(f"combinar espera (conteúdo, Coleitura); veio {tipos}")
        tc = triplas_por_execucao.get(c) or list(vizinhos(c)[2])
        tl = triplas_por_execucao.get(col) or list(vizinhos(col)[2])
        s = amostra.similaridade({"conteudo": tc, "coleitura": tl}, cfg.alfa)
        combinada = amostra.avaliar(s, [beta])[beta] | {
            "conteudo": c,
            "coleitura": col,
            "alfa": cfg.alfa,
            "beta": beta,
        }
        log.info(
            "Combinação %d + %d (α = %s): NDCG@20 %.4f", c, col, cfg.alfa, combinada["ndcg@20"]
        )
        if varredura:
            assert coleitura is not None
            minimo = _parametros_da_coleitura(_parametros(conn, col))[2]
            linhas = _varrer(amostra, tc, coleitura, minimo)
            combinada["melhor"] = max(linhas, key=lambda x: x["ndcg@20"])
        for e in combinar:
            resultado[e] = _gravar(conn, e, {"combinada": combinada})
            modelos.setdefault(e, _modelo(conn, e))

    relatorio = _escrever_relatorio(
        pasta_relatorios, resultado, modelos, pop, divisao, combinada, linhas
    )
    return ResultadoAvaliacao(resultado, pop, relatorio, combinada, linhas)


def _parametros(conn: Connection, execucao: int) -> dict:
    return (
        conn.execute(
            text("SELECT parametros FROM execucao_modelo WHERE id = :e"), {"e": execucao}
        ).scalar_one()
        or {}
    )


def _modelo(conn: Connection, execucao: int) -> str:
    return conn.execute(
        text("SELECT modelo FROM execucao_modelo WHERE id = :e"), {"e": execucao}
    ).scalar_one()


def _parametros_da_coleitura(parametros: dict) -> tuple[int, float, int]:
    return (
        int(parametros["k"]),
        float(parametros["lambda"]),
        int(parametros.get("min_coleitores", MIN_COLEITORES)),
    )


def _gravar(conn: Connection, execucao: int, m: dict) -> dict:
    """Junta às métricas que já existiam (o teste entre idiomas do bake-off fica)."""
    return conn.execute(
        text(
            "UPDATE execucao_modelo "
            "SET metricas = coalesce(metricas, '{}'::jsonb) || CAST(:m AS jsonb) "
            "WHERE id = :e RETURNING metricas"
        ),
        {"m": json.dumps(m), "e": execucao},
    ).scalar_one()


def _varrer(
    amostra: _Amostra, conteudo: list, coleitura: _ColeituraNoTreino, min_coleitores: int
) -> list[dict]:
    """A grade do §9.4: α × β × K × λ × tabela de pesos. Com α = 1 a Coleitura não entra,
    e K e λ não se aplicam."""
    linhas = []
    for alfa in VARREDURA_ALFA:
        grade = (
            [(None, None)] if alfa == 1 else list(itertools.product(VARREDURA_K, VARREDURA_LAMBDA))
        )
        for k, lam in grade:
            vizinhos: dict[str, list[tuple]] = {"conteudo": conteudo}
            if k is not None:
                vizinhos["coleitura"] = coleitura.triplas(k, lam, min_coleitores)
            s = amostra.similaridade(vizinhos, alfa)
            for tabela in TABELAS_DE_PESO:
                for b, m in amostra.avaliar(s, VARREDURA_BETA, tabela).items():
                    linhas.append(
                        {"alfa": alfa, "beta": b, "k": k, "lambda": lam, "pesos": tabela}
                        | {x: m[x] for x in _METRICAS}
                    )
        log.info("Varredura: α = %s pronto", alfa)
    return linhas


# --- relatório ---


def _br(x: float) -> str:
    return f"{x:.4f}".replace(".", ",")


def _num(x: float | None) -> str:
    return "—" if x is None else f"{x:g}".replace(".", ",")


def _escrever_relatorio(
    pasta: Path,
    metricas: dict[int, dict],
    modelos: dict[int, str],
    pop: dict,
    divisao: Divisao,
    combinada: dict | None = None,
    varredura: list[dict] | None = None,
) -> Path:
    isoladas = {e: m for e, m in metricas.items() if "ndcg@20" in m}
    beta = next(iter(isoladas.values()))["beta"] if isoladas else None
    linhas = [
        f"# Avaliação offline — {date.today():%d/%m/%Y}",
        "",
        f"Divisão (SPEC §9.1): {json.dumps(divisao.parametros, ensure_ascii=False)}.",
        f"Leitores com teste: {pop['leitores']}.",
        "",
        f"Pontuação com β = {_num(beta)} (peso da popularidade, ADR 0006) e a tabela de "
        "pesos do PRD. A Coleitura é recalculada só com as Notas de treino.",
        "",
        "| Execução | Modelo | NDCG@20 | Recall@20 | Cobertura | Extras |",
        "|---|---|---|---|---|---|",
    ]
    base = (
        *("ndcg@20", "recall@20", "cobertura", "leitores", "divisao", "avaliado_em"),
        *("beta", "varredura_beta", "combinada"),
    )
    for e, m in sorted(isoladas.items(), key=lambda x: -x[1]["ndcg@20"]):
        extras = ", ".join(
            f"{k}: {v}" for k, v in m.items() if k not in base and not k.startswith("baseline")
        )
        linhas.append(
            f"| {e} | `{modelos[e]}` | {_br(m['ndcg@20'])} | {_br(m['recall@20'])} "
            f"| {_br(m['cobertura'])} | {extras} |"
        )
    linhas.append(
        f"| — | Popularidade (baseline) | {_br(pop['ndcg@20'])} | {_br(pop['recall@20'])} "
        f"| {_br(pop['cobertura'])} | |"
    )
    if isoladas:
        betas = sorted(next(iter(isoladas.values()))["varredura_beta"], key=float)
        linhas += [
            "",
            "## NDCG@20 (cobertura) por β",
            "",
            "| Execução | " + " | ".join(f"β = {_num(float(b))}" for b in betas) + " |",
            "|---|" + "---|" * len(betas),
        ]
        for e, m in sorted(isoladas.items()):
            v = m["varredura_beta"]
            celulas = [f"{_br(v[b]['ndcg@20'])} ({_br(v[b]['cobertura'])})" for b in betas]
            linhas.append(f"| {e} | " + " | ".join(celulas) + " |")
    if combinada:
        linhas += _secao_combinada(combinada, isoladas, varredura or [])

    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"avaliacao-{date.today():%Y-%m-%d}.md"
    arquivo.write_bytes(("\n".join(linhas) + "\n").encode("utf-8"))
    if varredura:
        with (pasta / f"varredura-{date.today():%Y-%m-%d}.csv").open(
            "w", newline="", encoding="utf-8"
        ) as f:
            escritor = csv.DictWriter(f, fieldnames=list(varredura[0]), lineterminator="\n")
            escritor.writeheader()
            escritor.writerows(varredura)
    return arquivo


def _secao_combinada(combinada: dict, isoladas: dict[int, dict], varredura: list[dict]):
    c, col, alfa = combinada["conteudo"], combinada["coleitura"], combinada["alfa"]
    melhor_isolada = max((isoladas[e]["ndcg@20"] for e in (c, col) if e in isoladas), default=None)
    linhas = [
        "",
        f"## Combinação: conteúdo {c} + Coleitura {col}",
        "",
        f"Com α = {_num(alfa)} (config) e β = {_num(combinada['beta'])}: NDCG@20 "
        f"{_br(combinada['ndcg@20'])}, Recall@20 {_br(combinada['recall@20'])}, "
        f"cobertura {_br(combinada['cobertura'])}.",
    ]
    if melhor_isolada is not None:
        passou = combinada["ndcg@20"] >= melhor_isolada
        linhas.append(
            f"Critério do §14 (combinado ≥ melhor isolado, {_br(melhor_isolada)}): "
            f"{'cumprido' if passou else 'não cumprido'}."
        )
    if not varredura:
        return linhas

    def chave(x: dict) -> tuple:
        return (x["alfa"], x["beta"], x["k"], x["lambda"], x["pesos"])

    por_chave = {chave(x): x for x in varredura}
    k0, l0 = next((x["k"], x["lambda"]) for x in varredura if x["k"] is not None)
    m = combinada.get("melhor") or max(varredura, key=lambda x: x["ndcg@20"])
    linhas += [
        "",
        "### Varredura (SPEC §9.4)",
        "",
        f"{len(varredura)} configurações; a grade completa está no CSV do mesmo dia. "
        "K e λ variam só a Coleitura (recalculada no treino); o conteúdo usa os "
        "Vizinhos gravados da execução.",
        "",
        f"**Melhor NDCG@20:** {_br(m['ndcg@20'])} com α = {_num(m['alfa'])}, "
        f"β = {_num(m['beta'])}, K = {_num(m['k'])}, λ = {_num(m['lambda'])}, pesos "
        f"`{m['pesos']}` (cobertura {_br(m['cobertura'])}).",
        "",
        "As 10 melhores:",
        "",
        "| α | β | K | λ | Pesos | NDCG@20 | Recall@20 | Cobertura |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for x in sorted(varredura, key=lambda x: -x["ndcg@20"])[:10]:
        linhas.append(
            f"| {_num(x['alfa'])} | {_num(x['beta'])} | {_num(x['k'])} | {_num(x['lambda'])} "
            f"| {x['pesos']} | {_br(x['ndcg@20'])} | {_br(x['recall@20'])} "
            f"| {_br(x['cobertura'])} |"
        )

    # α × β, com o K e o λ do melhor e os pesos do PRD.
    k_m, l_m = (m["k"], m["lambda"]) if m["k"] is not None else (k0, l0)
    linhas += [
        "",
        f"#### NDCG@20 (cobertura) por α e β — K = {_num(k_m)}, λ = {_num(l_m)}, pesos do PRD",
        "",
        "| α | " + " | ".join(f"β = {_num(b)}" for b in VARREDURA_BETA) + " |",
        "|---|" + "---|" * len(VARREDURA_BETA),
    ]
    for a in VARREDURA_ALFA:
        k, lam = (None, None) if a == 1 else (k_m, l_m)
        celulas = [
            f"{_br(x['ndcg@20'])} ({_br(x['cobertura'])})"
            if (x := por_chave.get((a, b, k, lam, "prd")))
            else "—"
            for b in VARREDURA_BETA
        ]
        linhas.append(f"| {_num(a)} | " + " | ".join(celulas) + " |")

    # K × λ, com o α e o β do melhor (ou α = 0,5 se o melhor for só conteúdo).
    a_m = m["alfa"] if m["alfa"] < 1 else 0.5
    linhas += [
        "",
        f"#### NDCG@20 por K e λ — α = {_num(a_m)}, β = {_num(m['beta'])}, pesos do PRD",
        "",
        "| K | " + " | ".join(f"λ = {_num(lam)}" for lam in VARREDURA_LAMBDA) + " |",
        "|---|" + "---|" * len(VARREDURA_LAMBDA),
    ]
    for k in VARREDURA_K:
        celulas = [
            _br(x["ndcg@20"]) if (x := por_chave.get((a_m, m["beta"], k, lam, "prd"))) else "—"
            for lam in VARREDURA_LAMBDA
        ]
        linhas.append(f"| {k} | " + " | ".join(celulas) + " |")

    linhas += ["", "#### Melhor NDCG@20 por tabela de pesos", ""]
    for tabela, pesos in TABELAS_DE_PESO.items():
        x = max((v for v in varredura if v["pesos"] == tabela), key=lambda v: v["ndcg@20"])
        linhas.append(
            f"- `{tabela}` {dict(pesos)}: {_br(x['ndcg@20'])} (α = {_num(x['alfa'])}, "
            f"β = {_num(x['beta'])}, K = {_num(x['k'])}, λ = {_num(x['lambda'])})"
        )
    return linhas
