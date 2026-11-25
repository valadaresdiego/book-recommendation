"""`calcular-tecnico`: os Vizinhos de cada Obra entre as Obras técnicas (SPEC §8.8, ADR 0009).

Usa o modelo da execução de conteúdo ativa. Gera os embeddings que faltam (as Obras
técnicas da Open Library carregadas depois do último `calcular-conteudo`), liga cada Obra
do Catálogo com embedding às 50 Obras técnicas mais parecidas e cria uma execução `tecnico`
que já entra **ativa**: sem Coleitura, não há avaliação offline para comparar (ADR 0009).
"""

import json
import logging
from dataclasses import dataclass

import numpy as np
from sqlalchemy import Connection, text

from recomendador.catalogo.generos import SLUG_TECNOLOGIA
from recomendador.catalogo.texto import normalizar
from recomendador.pipeline.conteudo import MAX_MESMO_AUTOR, K, top_vizinhos
from recomendador.pipeline.execucoes import _vetor, copiar_vizinhos
from recomendador.recomendacao.embeddings import Codificador
from recomendador.recomendacao.interativo import ModeloDiferente
from recomendador.recomendacao.pontuacao import escala
from recomendador.recomendacao.texto import carregar_dados, texto_da_obra

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResumoTecnico:
    execucao_id: int | None  # None: não havia execução de conteúdo ativa ou Obra técnica
    obras: int  # Obras com Vizinhos técnicos
    tecnicas: int  # Obras técnicas com embedding (as candidatas)
    vizinhos: int
    embeddings_novos: int
    sem_embedding: int  # Obras técnicas que ficaram de fora por falta de embedding


_VAZIO = ResumoTecnico(None, 0, 0, 0, 0, 0)


def _ids_tecnicos(conn: Connection) -> set[int]:
    return set(
        conn.execute(
            text(
                "SELECT og.obra_id FROM obra_genero og JOIN genero g ON g.id = og.genero_id "
                "WHERE g.slug = :s"
            ),
            {"s": SLUG_TECNOLOGIA},
        ).scalars()
    )


def _gerar_embeddings(
    conn: Connection, codificador: Codificador, execucao: int, obra_ids: list[int]
) -> int:
    dados = carregar_dados(conn, obra_ids)
    ids = list(dados)
    log.info("Embeddings de %d Obras técnicas com %s", len(ids), codificador.nome)
    e = codificador.codificar([texto_da_obra(dados[i]) for i in ids])
    conn.execute(
        text(
            "UPDATE obra SET embedding = CAST(:v AS vector), embedding_execucao_id = :e "
            "WHERE id = :o"
        ),
        [{"o": o, "v": _vetor(v), "e": execucao} for o, v in zip(ids, e, strict=True)],
    )
    return len(ids)


def calcular_tecnico(
    conn: Connection,
    codificador: Codificador | None = None,
    k: int = K,
    max_mesmo_autor: int = MAX_MESMO_AUTOR,
) -> ResumoTecnico:
    """Cria e ativa a execução `tecnico`. Sem `codificador`, as Obras técnicas sem embedding
    do modelo ativo ficam de fora (o `ativar` chama assim, sem carregar o modelo)."""
    ativa = conn.execute(
        text("SELECT id, modelo FROM execucao_modelo WHERE ativa AND tipo = 'conteudo'")
    ).one_or_none()
    if ativa is None:
        log.warning("Sem execução de conteúdo ativa: os Vizinhos técnicos ficam para depois")
        return _VAZIO
    tecnicas = _ids_tecnicos(conn)
    if not tecnicas:
        log.info("Nenhuma Obra técnica no Catálogo: rode `carregar-tecnicas` antes")
        return _VAZIO

    # Só as da Open Library: a do Leitor fica pendente para o app ou o `atualizar`, que
    # gravam o embedding junto com os Vizinhos de conteúdo dela (§7.3, §10).
    faltam = list(
        conn.execute(
            text(
                "SELECT id FROM obra WHERE id = ANY(:t) AND origem = 'open_library' "
                "AND embedding_execucao_id IS DISTINCT FROM :e ORDER BY id"
            ),
            {"t": sorted(tecnicas), "e": ativa.id},
        ).scalars()
    )
    novos = 0
    if faltam and codificador is not None:
        if codificador.nome != ativa.modelo:
            raise ModeloDiferente(f"Execução ativa usa {ativa.modelo}, não {codificador.nome}")
        novos = _gerar_embeddings(conn, codificador, ativa.id, faltam)
    elif faltam:
        log.warning(
            "%d Obras técnicas sem embedding do modelo ativo ficam de fora: "
            "rode `calcular-tecnico`",
            len(faltam),
        )

    linhas = conn.execute(
        text(
            "SELECT id, autores[1] AS autor, embedding::text AS e FROM obra "
            "WHERE embedding IS NOT NULL AND embedding_execucao_id = :e ORDER BY id"
        ),
        {"e": ativa.id},
    ).all()
    ids = [r.id for r in linhas]
    colunas = np.array([i for i, o in enumerate(ids) if o in tecnicas], dtype=np.int64)
    sem_embedding = len(tecnicas) - len(colunas)
    if not len(colunas):
        log.warning("Nenhuma Obra técnica com embedding: nada a calcular")
        return ResumoTecnico(None, 0, 0, 0, novos, sem_embedding)
    e = np.array([json.loads(r.e) for r in linhas], dtype=np.float32)
    e /= np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-12)
    autores = [normalizar(r.autor) or None if r.autor else None for r in linhas]
    vizinhos = top_vizinhos(e, autores, k, max_mesmo_autor, colunas)

    parametros = {
        "k": k,
        "max_mesmo_autor": max_mesmo_autor,
        "conteudo_execucao_id": ativa.id,
        "escala": escala(s for lista in vizinhos for _, s in lista),
    }
    execucao_id = conn.execute(
        text(
            "INSERT INTO execucao_modelo (tipo, modelo, parametros) "
            "VALUES ('tecnico', :m, CAST(:p AS jsonb)) RETURNING id"
        ),
        {"m": ativa.modelo, "p": json.dumps(parametros)},
    ).scalar_one()
    gravar = [
        (execucao_id, ids[i], ids[j], sim, posicao)
        for i, lista in enumerate(vizinhos)
        for posicao, (j, sim) in enumerate(lista, 1)
    ]
    copiar_vizinhos(conn, gravar)
    conn.execute(text("UPDATE execucao_modelo SET ativa = false WHERE tipo = 'tecnico'"))
    conn.execute(text("UPDATE execucao_modelo SET ativa = true WHERE id = :e"), {"e": execucao_id})
    log.info(
        "Execução %d (tecnico, ativa): %d Vizinhos de %d Obras entre %d Obras técnicas",
        execucao_id,
        len(gravar),
        len(ids),
        len(colunas),
    )
    if sem_embedding:
        log.warning("%d Obras técnicas sem embedding ficaram de fora", sem_embedding)
    return ResumoTecnico(execucao_id, len(ids), len(colunas), len(gravar), novos, sem_embedding)
