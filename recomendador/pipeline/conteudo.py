"""`calcular-conteudo`: embeddings e Vizinhos de conteúdo de todo o Catálogo (SPEC §8.2).

Cria uma execução **inativa**. Os Vizinhos vão para `vizinho`; os embeddings ficam em
`data/embeddings/conteudo-<execucao>.npz` e só entram em `obra.embedding` quando a
execução é ativada (`pipeline.execucoes.ativar`). Assim o bake-off pode calcular vários
modelos sem mexer no que o app usa.
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import Connection, text

from recomendador.catalogo.texto import normalizar
from recomendador.recomendacao.embeddings import Codificador
from recomendador.recomendacao.texto import carregar_dados, texto_da_obra

log = logging.getLogger(__name__)

K = 50
MAX_MESMO_AUTOR = 5
_BLOCO = 1024


@dataclass(frozen=True)
class ResumoConteudo:
    execucao_id: int
    obras: int
    vizinhos: int
    segundos_embedding: float


def top_vizinhos(
    e: np.ndarray, autores: list[str | None], k: int = K, max_mesmo_autor: int = MAX_MESMO_AUTOR
) -> list[list[tuple[int, float]]]:
    """Os `k` vizinhos de cada linha de `e` (norma 1) por cosseno, do mais parecido ao menos.

    Exclui a própria Obra e aceita no máximo `max_mesmo_autor` Obras do mesmo autor dela
    (senão uma série domina a lista). `autores[i]` é o primeiro autor normalizado.
    """
    n = len(e)
    folga = min(n, 3 * k + 1)
    saida: list[list[tuple[int, float]]] = []
    for inicio in range(0, n, _BLOCO):
        sims = e[inicio : inicio + _BLOCO] @ e.T
        for desloc, linha in enumerate(sims):
            i = inicio + desloc
            saida.append(_escolher(i, linha, autores, k, max_mesmo_autor, folga))
    return saida


def _escolher(
    i: int, linha: np.ndarray, autores: list[str | None], k: int, max_autor: int, folga: int
) -> list[tuple[int, float]]:
    candidatos = np.argpartition(-linha, folga - 1)[:folga] if folga < len(linha) else None
    while True:
        ordem = (
            candidatos[np.argsort(-linha[candidatos], kind="stable")]
            if candidatos is not None
            else np.argsort(-linha, kind="stable")
        )
        escolhidos: list[tuple[int, float]] = []
        do_autor = 0
        for j in ordem:
            if j == i:
                continue
            if autores[i] is not None and autores[j] == autores[i]:
                if do_autor >= max_autor:
                    continue
                do_autor += 1
            escolhidos.append((int(j), float(linha[j])))
            if len(escolhidos) == k:
                return escolhidos
        if candidatos is None:  # já olhou a linha inteira
            return escolhidos
        candidatos = None  # faltou: o autor tinha muitas Obras entre as mais parecidas


def calcular_conteudo(
    conn: Connection,
    codificador: Codificador,
    pasta: Path,
    k: int = K,
    max_mesmo_autor: int = MAX_MESMO_AUTOR,
) -> ResumoConteudo:
    dados = carregar_dados(conn)
    ids = list(dados)
    log.info("Embeddings de %d Obras com %s", len(ids), codificador.nome)
    inicio = time.monotonic()
    e = codificador.codificar([texto_da_obra(dados[i]) for i in ids])
    segundos = time.monotonic() - inicio
    log.info("  %.0f s (%.1f Obras/s)", segundos, len(ids) / max(segundos, 1e-9))

    autores = [normalizar(dados[i].autores[0]) or None if dados[i].autores else None for i in ids]
    vizinhos = top_vizinhos(e, autores, k, max_mesmo_autor)

    parametros = {"k": k, "max_mesmo_autor": max_mesmo_autor, "dimensao": int(e.shape[1])}
    execucao_id = conn.execute(
        text(
            "INSERT INTO execucao_modelo (tipo, modelo, parametros) "
            "VALUES ('conteudo', :m, CAST(:p AS jsonb)) RETURNING id"
        ),
        {"m": codificador.nome, "p": json.dumps(parametros)},
    ).scalar_one()
    linhas = [
        (execucao_id, ids[i], ids[j], sim, posicao)
        for i, lista in enumerate(vizinhos)
        for posicao, (j, sim) in enumerate(lista, 1)
    ]
    _copiar_vizinhos(conn, linhas)

    pasta.mkdir(parents=True, exist_ok=True)
    np.savez(
        pasta / f"conteudo-{execucao_id}.npz",
        ids=np.array(ids, dtype=np.int64),
        embeddings=e.astype(np.float16),
    )
    log.info("Execução %d: %d Vizinhos de %d Obras (inativa)", execucao_id, len(linhas), len(ids))
    return ResumoConteudo(execucao_id, len(ids), len(linhas), segundos)


def _copiar_vizinhos(conn: Connection, linhas: list[tuple]) -> None:
    """COPY na mesma transação: 500 mil linhas em segundos."""
    cursor = conn.connection.driver_connection.cursor()
    with cursor.copy(
        "COPY vizinho (execucao_id, obra_id, vizinho_id, similaridade, posicao) FROM STDIN"
    ) as copia:
        for linha in linhas:
            copia.write_row(linha)
