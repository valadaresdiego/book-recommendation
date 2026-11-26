"""Embedding e Vizinhos de conteúdo de uma Obra do Leitor, na hora (SPEC §7.3).

A Obra entra na execução de conteúdo **ativa**, com o mesmo modelo dela, e os Vizinhos
vêm de um KNN no pgvector (HNSW) restrito às Obras da Base de coleitura. Com uma execução
`tecnico` ativa, a Obra ganha também os Vizinhos técnicos, entre as Obras técnicas (§8.8).
"""

from sqlalchemy import Connection, text

from recomendador.catalogo.generos import SLUG_TECNOLOGIA
from recomendador.catalogo.texto import normalizar
from recomendador.recomendacao.embeddings import Codificador, vetor_pgvector
from recomendador.recomendacao.texto import carregar_dados, hash_do_texto, texto_da_obra

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


def obras_desatualizadas(conn: Connection, obra_ids: list[int] | None = None) -> list[int]:
    """As Obras do Leitor (as pedidas, ou todas) cujo embedding não é o do texto atual na
    execução de conteúdo ativa: sem embedding dela, ou com um texto diferente do que virou
    o embedding (`embedding_texto_hash`). Sem execução ativa, nenhuma."""
    ativa = _ativa(conn)
    if ativa is None:
        return []
    linhas = conn.execute(
        text(
            "SELECT id, embedding_execucao_id AS execucao, embedding_texto_hash AS hash "
            "FROM obra WHERE origem = 'leitor' "
            "AND (CAST(:ids AS bigint[]) IS NULL OR id = ANY(:ids)) ORDER BY id"
        ),
        {"ids": obra_ids},
    ).all()
    em_dia = [r for r in linhas if r.execucao == ativa[0] and r.hash is not None]
    dados = carregar_dados(conn, [r.id for r in em_dia]) if em_dia else {}
    mudaram = {r.id for r in em_dia if r.hash != hash_do_texto(texto_da_obra(dados[r.id]))}
    return [r.id for r in linhas if r.execucao != ativa[0] or r.hash is None or r.id in mudaram]


def pendente(conn: Connection, obra_id: int) -> bool:
    """Obra do Leitor sem o embedding do texto atual na execução de conteúdo ativa."""
    return bool(obras_desatualizadas(conn, [obra_id]))


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
    texto = texto_da_obra(dados)
    vetor = vetor_pgvector(codificador.codificar([texto])[0])
    conn.execute(
        text(
            "UPDATE obra SET embedding = CAST(:v AS vector), embedding_execucao_id = :e, "
            "embedding_texto_hash = :h WHERE id = :o"
        ),
        {"v": vetor, "e": execucao, "h": hash_do_texto(texto), "o": obra_id},
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
    feitos = _gravar_vizinhos(
        conn, execucao, obra_id, _limitar(candidatas, autor, k, max_mesmo_autor)
    )
    if (tecnico := _tecnico_ativo(conn)) is not None:
        # KNN exato: as Obras técnicas são poucas mil, e o filtro tiraria do HNSW quase tudo.
        tecnicas = conn.execute(
            text(
                """
                SELECT o.id, o.autores[1] AS autor,
                       1 - (o.embedding <=> CAST(:v AS vector)) AS sim
                FROM obra o
                JOIN obra_genero og ON og.obra_id = o.id
                JOIN genero g ON g.id = og.genero_id AND g.slug = :s
                WHERE o.embedding IS NOT NULL AND o.id <> :o
                ORDER BY 1 - (o.embedding <=> CAST(:v AS vector)) DESC, o.id
                LIMIT :n
                """
            ),
            {"v": vetor, "o": obra_id, "n": 3 * k, "s": SLUG_TECNOLOGIA},
        ).all()
        _gravar_vizinhos(conn, tecnico, obra_id, _limitar(tecnicas, autor, k, max_mesmo_autor))
    return feitos


def _tecnico_ativo(conn: Connection) -> int | None:
    return conn.execute(
        text("SELECT id FROM execucao_modelo WHERE ativa AND tipo = 'tecnico'")
    ).scalar_one_or_none()


def _limitar(
    candidatas, autor: str | None, k: int, max_mesmo_autor: int
) -> list[tuple[int, float]]:
    """As `k` primeiras, com no máximo `max_mesmo_autor` do autor da Obra (§8.2)."""
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
    return escolhidas


def _gravar_vizinhos(
    conn: Connection, execucao: int, obra_id: int, escolhidas: list[tuple[int, float]]
) -> int:
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
