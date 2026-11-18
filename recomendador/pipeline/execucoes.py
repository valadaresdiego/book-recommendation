"""`ativar`: troca a execução ativa de um tipo (SPEC §4 e §9.4)."""

import logging
from pathlib import Path

import numpy as np
from sqlalchemy import Connection, text

log = logging.getLogger(__name__)

METRICA = "ndcg@20"


class AtivacaoRecusada(RuntimeError):
    pass


def ativar(
    conn: Connection, execucao_id: int, pasta_embeddings: Path, forcar: bool = False
) -> None:
    """Torna `execucao_id` a ativa do seu tipo, numa transação só.

    Sem `forcar`, só ativa se a execução foi avaliada e o NDCG@20 dela é ≥ ao da ativa do
    mesmo tipo. Numa execução de conteúdo, os embeddings dela passam para `obra.embedding`;
    as Obras que ela não cobre (adicionadas depois do cálculo) ficam sem embedding, à espera
    do passo 2 do `atualizar` (SPEC §10).
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
    if not forcar:
        _conferir_metricas(conn, execucao_id, execucao.tipo, execucao.metricas)

    conn.execute(
        text("UPDATE execucao_modelo SET ativa = false WHERE tipo = CAST(:t AS tipo_execucao)"),
        {"t": execucao.tipo},
    )
    conn.execute(text("UPDATE execucao_modelo SET ativa = true WHERE id = :e"), {"e": execucao_id})
    if execucao.tipo == "conteudo":
        _copiar_embeddings(conn, execucao_id, pasta_embeddings)
    log.info("Execução %d (%s) ativada", execucao_id, execucao.tipo)


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
        [{"o": int(o), "v": _vetor(v), "e": execucao_id} for o, v in zip(ids, e, strict=True)],
    )


def _vetor(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6g}" for x in v) + "]"
