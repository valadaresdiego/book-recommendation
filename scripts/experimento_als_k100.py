"""Experimento: K = 100 no conteúdo e ALS (implicit) no lugar da Coleitura item-item.

Mesmo protocolo do §9 (5.000 leitores, semente 42, Coleitura só no treino). Só lê o banco.
Rodar da raiz do projeto: uv run --with implicit python <este arquivo> <saida.csv>
"""

import csv
import logging
import sys
import time
from pathlib import Path

import numpy as np
from scipy import sparse
from sqlalchemy import create_engine, text

from recomendador.catalogo.texto import normalizar
from recomendador.config import config
from recomendador.pipeline import avaliacao as av
from recomendador.pipeline.conteudo import top_vizinhos

logging.basicConfig(level=logging.WARNING)
SAIDA = Path(sys.argv[1])
BETAS = (0.0, 0.25)
linhas: list[dict] = []
t0 = time.time()


def registrar(nome: str, metricas: dict[float, dict], **extra) -> None:
    for b, m in metricas.items():
        linha = {"config": nome, "beta": b, **extra} | {k: m[k] for k in av._METRICAS}
        linhas.append(linha)
        print(
            f"[{time.time() - t0:6.0f}s] {nome:55} β={b:<4} NDCG@20 {m['ndcg@20']:.4f} "
            f"recall {m['recall@20']:.4f} cobertura {m['cobertura']:.1%}",
            flush=True,
        )
    with SAIDA.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=sorted({k for x in linhas for k in x}))
        w.writeheader()
        w.writerows(linhas)


def top_k_cosseno(v: np.ndarray, ids: np.ndarray, k: int) -> list[tuple]:
    """Os k vizinhos de maior cosseno > 0 de cada item, sem ele mesmo."""
    v = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
    triplas = []
    for inicio in range(0, len(v), 1000):
        s = v[inicio : inicio + 1000] @ v.T
        for d, linha in enumerate(s):
            i = inicio + d
            linha[i] = -np.inf
            melhores = np.argpartition(-linha, k)[:k]
            melhores = melhores[np.argsort(-linha[melhores])]
            triplas += [
                (int(ids[i]), int(ids[j]), float(linha[j])) for j in melhores if linha[j] > 0
            ]
    return triplas


eng = create_engine(config().database_url)
with eng.connect() as conn:
    notas = av.carregar_notas(conn, Path("data/raw/notas.parquet"))
    divisao = av.dividir(notas, n_leitores=5000)
    amostra = av._Amostra(conn, divisao)
    treino = av.notas_de_treino(notas, divisao)
    coleitura = av._ColeituraNoTreino(treino, amostra.indice)
    col_k20 = coleitura.triplas(20, 10, 5)
    conteudo_db = [
        tuple(r)
        for r in conn.execute(
            text("SELECT obra_id, vizinho_id, similaridade FROM vizinho WHERE execucao_id = 1")
        )
    ]
    autor_de = dict(
        conn.execute(text("SELECT id, autores[1] FROM obra WHERE origem = 'base'")).all()
    )
print(
    f"[{time.time() - t0:6.0f}s] dados carregados; popularidade {amostra.popular()['ndcg@20']:.4f}"
)

# --- referência: o que está no ar ---
registrar(
    "coleitura item-item K20 λ10 (ativa)",
    amostra.avaliar(amostra.similaridade({"coleitura": col_k20}, 0.0), BETAS),
)
registrar(
    "conteúdo K50 gravado (ativa)",
    amostra.avaliar(amostra.similaridade({"conteudo": conteudo_db}, 1.0), BETAS),
)
for alfa in (0.25, 0.5):
    s = amostra.similaridade({"conteudo": conteudo_db, "coleitura": col_k20}, alfa)
    registrar(
        f"mistura α={alfa}: conteúdo K50 gravado + item-item", amostra.avaliar(s, BETAS), alfa=alfa
    )

# --- K = 100 no conteúdo ---
d = np.load("data/embeddings/conteudo-1.npz")
ids = d["ids"]
e = d["embeddings"].astype(np.float32)
e /= np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-12)
autores = [normalizar(autor_de.get(int(o)) or "") or None for o in ids]
for k in (50, 100):
    viz = top_vizinhos(e, autores, k, 5)
    triplas = [
        (int(ids[i]), int(ids[j]), float(s)) for i, lista in enumerate(viz) for j, s in lista
    ]
    registrar(
        f"conteúdo K{k} recalculado",
        amostra.avaliar(amostra.similaridade({"conteudo": triplas}, 1.0), BETAS),
        k=k,
    )
    for alfa in (0.25, 0.5):
        s = amostra.similaridade({"conteudo": triplas, "coleitura": col_k20}, alfa)
        registrar(
            f"mistura α={alfa}: conteúdo K{k} + item-item",
            amostra.avaliar(s, BETAS),
            alfa=alfa,
            k=k,
        )

# --- ALS ---
from implicit.als import AlternatingLeastSquares  # noqa: E402

itens = np.array(list(amostra.indice))
usuarios = {u: i for i, u in enumerate(sorted(treino.usuario_base.unique()))}
linhas_u = treino.usuario_base.map(usuarios).to_numpy()
colunas_i = treino.obra_id.map(amostra.indice).to_numpy()
entradas = {
    "todas": np.ones(len(treino), dtype=np.float32),
    "boas": (treino.nota.to_numpy() >= 4).astype(np.float32),
}
for nome_entrada, valores in entradas.items():
    mascara = valores > 0
    m = sparse.csr_matrix(
        (valores[mascara], (linhas_u[mascara], colunas_i[mascara])),
        shape=(len(usuarios), len(itens)),
    )
    for fatores in (64, 128, 256):
        for reg in (0.01, 0.1):
            modelo = AlternatingLeastSquares(
                factors=fatores, regularization=reg, iterations=15, random_state=42
            )
            t = time.time()
            modelo.fit(m, show_progress=False)
            print(
                f"  ALS {nome_entrada} f={fatores} reg={reg}: treino em {time.time() - t:.0f}s",
                flush=True,
            )
            vetores = np.asarray(modelo.item_factors)
            for k in (20, 50):
                als = top_k_cosseno(vetores, itens, k)
                nome = f"ALS {nome_entrada} f={fatores} reg={reg} K{k}"
                extra = {"entrada": nome_entrada, "fatores": fatores, "reg": reg, "k": k}
                registrar(
                    nome,
                    amostra.avaliar(amostra.similaridade({"coleitura": als}, 0.0), BETAS),
                    alfa=0.0,
                    **extra,
                )
                s = amostra.similaridade({"conteudo": conteudo_db, "coleitura": als}, 0.25)
                registrar(
                    f"mistura α=0.25: conteúdo K50 + {nome}",
                    amostra.avaliar(s, BETAS),
                    alfa=0.25,
                    **extra,
                )
print(f"[{time.time() - t0:6.0f}s] fim", flush=True)
