"""Passo 3 do `atualizar` (SPEC §10): embeddings e Vizinhos das Obras do Leitor pendentes.

Uma Obra fica pendente quando o cálculo na hora (§7.3) falhou, quando a execução de
conteúdo ativa mudou depois do cálculo dela, ou quando o texto dela mudou depois do
embedding (o enriquecimento pela Open Library, Gêneros novos).
"""

import logging
import time

from sqlalchemy import Connection

from recomendador.recomendacao.embeddings import Codificador
from recomendador.recomendacao.interativo import calcular_vizinhos_da_obra, obras_desatualizadas

log = logging.getLogger(__name__)


def obras_pendentes(conn: Connection) -> list[int]:
    return obras_desatualizadas(conn)


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
