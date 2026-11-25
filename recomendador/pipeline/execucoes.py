"""`ativar`: troca a execução ativa de um tipo (SPEC §4 e §9.4)."""

import logging
from pathlib import Path

import numpy as np
from sqlalchemy import Connection, text

from recomendador.recomendacao.embeddings import vetor_pgvector

log = logging.getLogger(__name__)

METRICA = "ndcg@20"
# SPEC §9.4: só compara NDCG@20 com a mesma divisão e a mesma configuração.
_MESMA_CONFIGURACAO = ("divisao", "beta")


class AtivacaoRecusada(RuntimeError):
    pass


def ativar(
    conn: Connection, execucao_id: int, pasta_embeddings: Path, forcar: bool = False
) -> None:
    """Torna `execucao_id` a ativa do seu tipo, numa transação só.

    Sem `forcar`, só ativa se a execução foi avaliada e o NDCG@20 dela é ≥ ao da ativa do
    mesmo tipo. Numa execução de conteúdo, os embeddings dela passam para `obra.embedding`;
    as Obras que ela não cobre (adicionadas depois do cálculo) ficam sem embedding, à espera
    do passo 2 do `atualizar` (SPEC §10). Em seguida os Vizinhos técnicos são refeitos com
    os embeddings novos (`calcular-tecnico`, §8.8). Uma execução `tecnico` não tem
    avaliação offline (ADR 0009) e é ativada sem o critério do §9.4.
    """
    execucao = conn.execute(
        text("SELECT tipo::text AS tipo, metricas, ativa FROM execucao_modelo WHERE id = :e"),
        {"e": execucao_id},
    ).one_or_none()
    if execucao is None:
        raise AtivacaoRecusada(f"Execução {execucao_id} não existe")
    if execucao.ativa:
        log.info("Execução %d já é a ativa", execucao_id)
        return
    if not forcar and execucao.tipo != "tecnico":
        _conferir_metricas(conn, execucao_id, execucao.tipo, execucao.metricas)

    conn.execute(
        text("UPDATE execucao_modelo SET ativa = false WHERE tipo = CAST(:t AS tipo_execucao)"),
        {"t": execucao.tipo},
    )
    conn.execute(text("UPDATE execucao_modelo SET ativa = true WHERE id = :e"), {"e": execucao_id})
    log.info("Execução %d (%s) ativada", execucao_id, execucao.tipo)
    if execucao.tipo == "conteudo":
        _copiar_embeddings(conn, execucao_id, pasta_embeddings)
        from recomendador.pipeline.tecnico import calcular_tecnico

        calcular_tecnico(conn)


def _conferir_metricas(conn: Connection, execucao_id: int, tipo: str, metricas: dict | None):
    if not metricas or METRICA not in metricas:
        raise AtivacaoRecusada(
            f"A execução {execucao_id} ainda não tem {METRICA}: rode `avaliar` antes, "
            "ou use --forcar"
        )
    ativa = conn.execute(
        text(
            "SELECT id, metricas FROM execucao_modelo "
            "WHERE ativa AND tipo = CAST(:t AS tipo_execucao)"
        ),
        {"t": tipo},
    ).one_or_none()
    if ativa is None or not ativa.metricas or METRICA not in ativa.metricas:
        return
    for chave in _MESMA_CONFIGURACAO:
        if metricas.get(chave) != ativa.metricas.get(chave):
            raise AtivacaoRecusada(
                f"As execuções {execucao_id} e {ativa.id} foram avaliadas com {chave} "
                f"diferente: rode `avaliar {execucao_id} {ativa.id}` antes, ou use --forcar"
            )
    nova, atual = metricas[METRICA], ativa.metricas[METRICA]
    if nova < atual:
        raise AtivacaoRecusada(
            f"{METRICA} da execução {execucao_id} ({_br(nova)}) é menor que o da ativa "
            f"{ativa.id} ({_br(atual)}). Use --forcar para ativar assim mesmo."
        )


def _br(x: float) -> str:
    return f"{x:.3f}".replace(".", ",")


def _copiar_embeddings(conn: Connection, execucao_id: int, pasta: Path) -> None:
    arquivo = pasta / f"conteudo-{execucao_id}.npz"
    if not arquivo.exists():
        raise AtivacaoRecusada(f"Embeddings da execução {execucao_id} não achados em {arquivo}")
    with np.load(arquivo) as dados:
        ids, e = dados["ids"], dados["embeddings"].astype(np.float32)
    conn.execute(text("UPDATE obra SET embedding = NULL, embedding_execucao_id = NULL"))
    conn.execute(
        text(
            "UPDATE obra SET embedding = CAST(:v AS vector), embedding_execucao_id = :e "
            "WHERE id = :o"
        ),
        [
            {"o": int(o), "v": vetor_pgvector(v), "e": execucao_id}
            for o, v in zip(ids, e, strict=True)
        ],
    )


def copiar_vizinhos(conn: Connection, linhas: list[tuple]) -> None:
    """Grava (execucao_id, obra_id, vizinho_id, similaridade, posicao) com COPY, na mesma
    transação: 500 mil linhas em segundos."""
    cursor = conn.connection.driver_connection.cursor()
    with cursor.copy(
        "COPY vizinho (execucao_id, obra_id, vizinho_id, similaridade, posicao) FROM STDIN"
    ) as copia:
        for linha in linhas:
            copia.write_row(linha)
