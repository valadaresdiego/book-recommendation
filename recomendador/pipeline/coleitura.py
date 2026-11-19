"""`calcular-coleitura`: Vizinhos de Coleitura por cosseno ajustado (SPEC §8.1).

    R[u,i]   = nota − média_do_leitor_u          (só nas Notas que existem)
    num[i,j] = Σ_u R[u,i]·R[u,j]                 → Rᵀ R
    n[i,j]   = nº de leitores com Nota em i e j  → Bᵀ B, B binária
    sim[i,j] = num[i,j] / (‖R[:,i]‖·‖R[:,j]‖) × n[i,j] / (n[i,j] + λ)

As normas usam todos os leitores de cada Obra. Pares com menos de `min_coleitores`
coleitores são zerados, e cada Obra guarda os `k` maiores `sim > 0`.

O produto é esparso e roda no CPU por blocos de Obras: com as 6 milhões de Notas do
goodbooks-10k, leva segundos, e a GPU não ganha nada.
"""

import json
import logging
from collections.abc import Hashable, Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from sqlalchemy import Connection, text

from recomendador.pipeline.execucoes import copiar_vizinhos
from recomendador.recomendacao.pontuacao import escala

log = logging.getLogger(__name__)

# Calibrados na avaliação de 19/11/2026 (ADR 0007).
K = 20
LAMBDA = 10
MIN_COLEITORES = 5
MODELO = "cosseno-ajustado"
_BLOCO = 1000


@dataclass(frozen=True)
class ResumoColeitura:
    execucao_id: int
    obras: int
    vizinhos: int


def vizinhos_de_coleitura[O: Hashable](
    notas: pd.DataFrame,
    indice: Mapping[O, int],
    k: int = K,
    lam: float = LAMBDA,
    min_coleitores: int = MIN_COLEITORES,
) -> list[list[tuple[int, float]]]:
    """Os `k` Vizinhos de Coleitura de cada Obra de `indice` (por posição), do mais
    parecido ao menos, só com similaridade > 0 e sem a própria Obra.

    `notas`: usuario_base, obra_id, nota. A média de cada leitor usa todas as Notas dele,
    mesmo as de Obras fora de `indice`.
    """
    r, b = _matrizes(notas, indice)
    normas = np.sqrt(np.asarray(r.multiply(r).sum(axis=0)).ravel())
    inversa = np.divide(1.0, normas, out=np.zeros_like(normas), where=normas > 0)
    rt, bt = r.T.tocsr(), b.T.tocsr()
    n = len(indice)
    saida: list[list[tuple[int, float]]] = []
    for inicio in range(0, n, _BLOCO):
        fim = min(n, inicio + _BLOCO)
        num = (rt[inicio:fim] @ r).toarray()
        coleitores = (bt[inicio:fim] @ b).toarray()
        encolhimento = np.divide(
            coleitores,
            coleitores + lam,
            out=np.zeros_like(coleitores),
            where=coleitores > 0,
        )
        sim = num * inversa[inicio:fim, None] * inversa[None, :] * encolhimento
        sim[coleitores < min_coleitores] = 0.0
        sim[np.arange(fim - inicio), np.arange(inicio, fim)] = 0.0
        saida += [_maiores(linha, k) for linha in sim]
    return saida


def _matrizes[O: Hashable](
    notas: pd.DataFrame, indice: Mapping[O, int]
) -> tuple[sparse.csr_matrix, sparse.csr_matrix]:
    """R (leitores × Obras, nota − média do leitor) e B (as mesmas posições, valendo 1)."""
    nota = notas["nota"].to_numpy(dtype=np.float64)
    media = pd.Series(nota).groupby(notas["usuario_base"].to_numpy()).transform("mean")
    residuo = nota - media.to_numpy()
    coluna = notas["obra_id"].map(indice)
    dentro = coluna.notna().to_numpy()
    leitor = pd.factorize(notas["usuario_base"].to_numpy()[dentro])[0]
    coluna = coluna.to_numpy()[dentro].astype(np.int64)
    forma = (int(leitor.max()) + 1 if len(leitor) else 0, len(indice))
    r = sparse.csr_matrix((residuo[dentro], (leitor, coluna)), shape=forma)
    b = sparse.csr_matrix((np.ones(len(leitor)), (leitor, coluna)), shape=forma)
    return r, b


def _maiores(linha: np.ndarray, k: int) -> list[tuple[int, float]]:
    positivos = np.flatnonzero(linha > 0)
    if len(positivos) > k:
        positivos = positivos[np.argpartition(-linha[positivos], k - 1)[:k]]
    ordem = positivos[np.lexsort((positivos, -linha[positivos]))]
    return [(int(j), float(linha[j])) for j in ordem]


def calcular_coleitura(
    conn: Connection,
    notas: pd.DataFrame,
    k: int = K,
    lam: float = LAMBDA,
    min_coleitores: int = MIN_COLEITORES,
) -> ResumoColeitura:
    """Calcula a Coleitura de todas as Obras com Nota em `notas` e grava os Vizinhos numa
    execução `tipo='coleitura'` **inativa**."""
    ids = sorted(int(o) for o in notas["obra_id"].unique())
    indice = {o: i for i, o in enumerate(ids)}
    log.info("Coleitura de %d Obras com %d Notas (λ = %s, K = %d)", len(ids), len(notas), lam, k)
    vizinhos = vizinhos_de_coleitura(notas, indice, k, lam, min_coleitores)

    parametros = {
        "k": k,
        "lambda": lam,
        "min_coleitores": min_coleitores,
        "escala": escala(s for lista in vizinhos for _, s in lista),
    }
    execucao_id = conn.execute(
        text(
            "INSERT INTO execucao_modelo (tipo, modelo, parametros) "
            "VALUES ('coleitura', :m, CAST(:p AS jsonb)) RETURNING id"
        ),
        {"m": MODELO, "p": json.dumps(parametros)},
    ).scalar_one()
    linhas = [
        (execucao_id, ids[i], ids[j], sim, posicao)
        for i, lista in enumerate(vizinhos)
        for posicao, (j, sim) in enumerate(lista, 1)
    ]
    copiar_vizinhos(conn, linhas)
    sem = sum(1 for lista in vizinhos if not lista)
    log.info(
        "Execução %d: %d Vizinhos de %d Obras, %d sem nenhum (inativa)",
        execucao_id,
        len(linhas),
        len(ids),
        sem,
    )
    return ResumoColeitura(execucao_id, len(ids), len(linhas))
