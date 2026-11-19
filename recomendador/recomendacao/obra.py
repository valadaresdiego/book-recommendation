"""Página da Obra (R5, SPEC §8.3): a Obra, a Nota do Leitor e os Vizinhos das execuções ativas."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

VIZINHOS_NA_PAGINA = 10


@dataclass(frozen=True)
class ObraVizinha:
    obra_id: int
    titulo_exibicao: str
    autores: tuple[str, ...]
    capa_url: str | None
    similaridade: float
    lido: bool  # está na Estante (selo "lido")


@dataclass(frozen=True)
class PaginaObra:
    obra_id: int
    titulo_exibicao: str
    titulo_original: str | None  # só quando difere do título de exibição
    autores: tuple[str, ...]
    ano: int | None
    descricao: str | None
    capa_url: str | None
    generos: tuple[str, ...]
    na_estante: bool
    nota: int | None
    parecidos: list[ObraVizinha]  # R5a: Vizinhos de conteúdo
    quem_leu: list[ObraVizinha]  # R5b: Vizinhos de Coleitura (vazio: a UI mostra o aviso)
    dispensada: bool = False  # R7: a página oferece "Desfazer"
    quero_ler: bool = False  # R8: está na lista Quero ler
    estou_lendo: bool = False  # R13: está na lista Estou lendo


_OBRA = text(
    """
    SELECT o.id, o.titulo, o.titulo_original, o.titulo_exibicao, o.autores, o.ano_original,
           o.descricao, o.capa_url,
           coalesce((SELECT array_agg(g.nome ORDER BY og.forca DESC)
                     FROM obra_genero og JOIN genero g ON g.id = og.genero_id
                     WHERE og.obra_id = o.id), '{}') AS generos,
           l.id IS NOT NULL AS na_estante, l.nota,
           EXISTS (SELECT 1 FROM dispensa d WHERE d.leitor_id = :leitor AND d.obra_id = o.id)
               AS dispensada,
           EXISTS (SELECT 1 FROM quero_ler q WHERE q.leitor_id = :leitor AND q.obra_id = o.id)
               AS quero_ler,
           EXISTS (SELECT 1 FROM estou_lendo el WHERE el.leitor_id = :leitor AND el.obra_id = o.id)
               AS estou_lendo
    FROM obra o
    LEFT JOIN leitura l ON l.obra_id = o.id AND l.leitor_id = :leitor
    WHERE o.id = :obra
    """
)

_VIZINHOS = text(
    """
    SELECT o.id, o.titulo_exibicao, o.autores, o.capa_url, v.similaridade,
           EXISTS (SELECT 1 FROM leitura l WHERE l.leitor_id = :leitor AND l.obra_id = o.id)
               AS lido
    FROM vizinho v
    JOIN execucao_modelo e
      ON e.id = v.execucao_id AND e.ativa AND e.tipo = CAST(:tipo AS tipo_execucao)
    JOIN obra o ON o.id = v.vizinho_id
    WHERE v.obra_id = :obra
    ORDER BY v.posicao
    LIMIT :limite
    """
)


def pagina_da_obra(conn: Connection, obra_id: int, leitor_id: uuid.UUID) -> PaginaObra | None:
    o = conn.execute(_OBRA, {"obra": obra_id, "leitor": leitor_id}).one_or_none()
    if o is None:
        return None
    original = o.titulo_original or (o.titulo if o.titulo != o.titulo_exibicao else None)
    if original and original.strip() == o.titulo_exibicao.strip():
        original = None
    return PaginaObra(
        obra_id=o.id,
        titulo_exibicao=o.titulo_exibicao,
        titulo_original=original,
        autores=tuple(o.autores),
        ano=o.ano_original,
        descricao=o.descricao,
        capa_url=o.capa_url,
        generos=tuple(o.generos),
        na_estante=o.na_estante,
        nota=o.nota,
        parecidos=_vizinhos(conn, obra_id, leitor_id, "conteudo"),
        quem_leu=_vizinhos(conn, obra_id, leitor_id, "coleitura"),
        dispensada=o.dispensada,
        quero_ler=o.quero_ler,
        estou_lendo=o.estou_lendo,
    )


def _vizinhos(conn: Connection, obra_id: int, leitor_id: uuid.UUID, tipo: str) -> list[ObraVizinha]:
    return [
        ObraVizinha(r.id, r.titulo_exibicao, tuple(r.autores), r.capa_url, r.similaridade, r.lido)
        for r in conn.execute(
            _VIZINHOS,
            {"obra": obra_id, "leitor": leitor_id, "tipo": tipo, "limite": VIZINHOS_NA_PAGINA},
        )
    ]
