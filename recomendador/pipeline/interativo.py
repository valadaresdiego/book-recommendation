"""Passo 2 do `atualizar` (SPEC §10): embeddings e Vizinhos das Obras do Leitor pendentes.

Uma Obra fica pendente quando o cálculo na hora (§7.3) falhou, ou quando a execução de
conteúdo ativa mudou depois do cálculo dela.
"""

import logging
import time

from sqlalchemy import Connection, text

from recomendador.recomendacao.embeddings import Codificador
from recomendador.recomendacao.interativo import calcular_vizinhos_da_obra

log = logging.getLogger(__name__)

_PENDENTES = text(
    """
    SELECT o.id FROM obra o
    JOIN execucao_modelo e ON e.ativa AND e.tipo = 'conteudo'
    WHERE o.origem = 'leitor' AND o.embedding_execucao_id IS DISTINCT FROM e.id
    ORDER BY o.id
    """
)


def obras_pendentes(conn: Connection) -> list[int]:
    return list(conn.execute(_PENDENTES).scalars())


def embeddings_pendentes(
    conn: Connection, codificador: Codificador, prazo: float | None = None
) -> int:
    """Calcula as pendentes até o `prazo` (`time.monotonic()`); devolve quantas fez."""
    feitas = 0
    for obra_id in obras_pendentes(conn):
        if prazo is not None and time.monotonic() > prazo:
            log.warning("Prazo do atualizar esgotado; o resto fica para a próxima abertura")
            break
        calcular_vizinhos_da_obra(conn, obra_id, codificador)
        feitas += 1
    if feitas:
        log.info("Embeddings de %d Obras do Leitor calculados", feitas)
    return feitas
