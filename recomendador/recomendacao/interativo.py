"""Embedding e Vizinhos de conteúdo de uma Obra do Leitor, na hora (SPEC §7.3).

A Obra entra na execução de conteúdo **ativa**, com o mesmo modelo dela, e os Vizinhos
vêm de um KNN no pgvector (HNSW) restrito às Obras da Base de coleitura.
"""

import numpy as np
from sqlalchemy import Connection, text

from recomendador.catalogo.texto import normalizar
from recomendador.recomendacao.embeddings import Codificador
from recomendador.recomendacao.texto import carregar_dados, texto_da_obra

K = 50
MAX_MESMO_AUTOR = 5


class ModeloDiferente(RuntimeError):
    """O codificador não é o modelo da execução de conteúdo ativa."""


def _ativa(conn: Connection) -> tuple[int, str] | None:
    linha = conn.execute(
        text("SELECT id, modelo FROM execucao_modelo WHERE ativa AND tipo = 'conteudo'")
    ).one_or_none()
    return (linha.id, linha.modelo) if linha else None


def modelo_de_conteudo_ativo(conn: Connection) -> str | None:
    """O modelo que o app precisa carregar para calcular embeddings, se houver execução ativa."""
    ativa = _ativa(conn)
    return ativa[1] if ativa else None


def pendente(conn: Connection, obra_id: int) -> bool:
    """Obra do Leitor sem embedding da execução de conteúdo ativa."""
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM obra o JOIN execucao_modelo e ON e.ativa AND e.tipo = 'conteudo' "
                "WHERE o.id = :o AND o.origem = 'leitor' "
                "AND o.embedding_execucao_id IS DISTINCT FROM e.id"
            ),
            {"o": obra_id},
        ).first()
    )


def carregar_codificador(nome: str) -> Codificador:
    """O modelo do Hugging Face (precisa do extra `ml`: `uv sync --extra ml`)."""
    from recomendador.recomendacao.embeddings import ModeloSentenceTransformers

    return ModeloSentenceTransformers(nome)


def calcular_vizinhos_da_obra(
    conn: Connection,
    obra_id: int,
    codificador: Codificador,
    k: int = K,
    max_mesmo_autor: int = MAX_MESMO_AUTOR,
) -> int:
    """Grava o embedding da Obra e os `k` Vizinhos dela na execução ativa. Devolve quantos.

    Sem execução de conteúdo ativa, não faz nada (devolve 0).
    """
    ativa = _ativa(conn)
    if ativa is None:
        return 0
    execucao, modelo = ativa
    if codificador.nome != modelo:
        raise ModeloDiferente(f"Execução ativa usa {modelo}, não {codificador.nome}")
    dados = carregar_dados(conn, [obra_id])[obra_id]
    vetor = _vetor(codificador.codificar([texto_da_obra(dados)])[0])
    conn.execute(
        text(
            "UPDATE obra SET embedding = CAST(:v AS vector), embedding_execucao_id = :e "
            "WHERE id = :o"
        ),
        {"v": vetor, "e": execucao, "o": obra_id},
    )
    # O HNSW devolve no máximo `ef_search` linhas; com folga para o limite por autor.
    conn.execute(text(f"SET LOCAL hnsw.ef_search = {max(40, 3 * k)}"))
    candidatas = conn.execute(
        text(
            """
            SELECT id, autores[1] AS autor, 1 - (embedding <=> CAST(:v AS vector)) AS sim
            FROM obra
            WHERE origem = 'base' AND embedding IS NOT NULL AND id <> :o
            ORDER BY embedding <=> CAST(:v AS vector)
            LIMIT :n
            """
        ),
        {"v": vetor, "o": obra_id, "n": 3 * k},
    ).all()
    autor = normalizar(dados.autores[0]) if dados.autores else None
    escolhidas: list[tuple[int, float]] = []
    do_autor = 0
    for c in candidatas:
        if autor and c.autor and normalizar(c.autor) == autor:
            if do_autor >= max_mesmo_autor:
                continue
            do_autor += 1
        escolhidas.append((c.id, float(c.sim)))
        if len(escolhidas) == k:
            break
    conn.execute(
        text("DELETE FROM vizinho WHERE execucao_id = :e AND obra_id = :o"),
        {"e": execucao, "o": obra_id},
    )
    if escolhidas:
        conn.execute(
            text("INSERT INTO vizinho VALUES (:e, :o, :v, :s, :p)"),
            [
                {"e": execucao, "o": obra_id, "v": v, "s": s, "p": p}
                for p, (v, s) in enumerate(escolhidas, 1)
            ],
        )
    return len(escolhidas)


def _vetor(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6g}" for x in v) + "]"
