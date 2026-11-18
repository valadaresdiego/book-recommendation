"""'Para você' (R4, SPEC §8.5): uma consulta SQL sobre as execuções ativas.

A soma das parcelas é multiplicada por (1 + popularidade)^β (ADR 0006).

A conta é a mesma de `recomendacao.pontuacao` (a da avaliação offline, §9); um teste
confere as duas.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from recomendador.config import PESO_DA_NOTA, config


@dataclass(frozen=True)
class Sugestao:
    obra_id: int
    titulo_exibicao: str
    autores: tuple[str, ...]
    capa_url: str | None
    ano: int | None
    pontuacao: float
    # O Motivo: a Leitura de Nota alta que mais contribuiu (o texto é montado na UI).
    motivo_obra_id: int
    motivo_titulo: str
    motivo_nota: int


@dataclass(frozen=True)
class ParaVoce:
    sugestoes: list[Sugestao]
    notas: int  # Leituras com Nota
    minimo: int  # Notas necessárias para sugerir
    execucoes: tuple[int, ...] = ()  # as ativas, para o evento `sugestao_exibida`

    @property
    def suficiente(self) -> bool:
        return self.notas >= self.minimo


_CONSULTA = text(
    """
    WITH pesos AS (
        SELECT * FROM unnest(CAST(:notas AS int[]), CAST(:pesos AS float8[])) AS p(nota, peso)
    ),
    leituras AS (
        SELECT l.obra_id, l.nota, p.peso
        FROM leitura l JOIN pesos p ON p.nota = l.nota
        WHERE l.leitor_id = :leitor AND p.peso <> 0
    ),
    parcelas AS (
        SELECT v.vizinho_id AS candidata, r.obra_id AS motivo, r.nota, r.peso,
               r.peso * sum(
                   CASE WHEN e.tipo = 'conteudo' THEN :alfa ELSE 1 - :alfa END * v.similaridade
               ) AS parcela
        FROM leituras r
        JOIN vizinho v ON v.obra_id = r.obra_id
        JOIN execucao_modelo e ON e.id = v.execucao_id AND e.ativa
        GROUP BY v.vizinho_id, r.obra_id, r.nota, r.peso
    ),
    pontos AS (
        SELECT p.candidata,
               sum(p.parcela) * power(1 + max(o.popularidade), :beta) AS pontuacao
        FROM parcelas p JOIN obra o ON o.id = p.candidata
        GROUP BY p.candidata
    ),
    motivos AS (
        SELECT DISTINCT ON (candidata) candidata, motivo, nota
        FROM parcelas WHERE parcela > 0 AND peso > 0
        ORDER BY candidata, parcela DESC, motivo
    )
    SELECT o.id, o.titulo_exibicao, o.autores, o.capa_url, o.ano_original, p.pontuacao,
           m.motivo, mo.titulo_exibicao AS motivo_titulo, m.nota AS motivo_nota
    FROM pontos p
    JOIN motivos m USING (candidata)
    JOIN obra o ON o.id = p.candidata
    JOIN obra mo ON mo.id = m.motivo
    WHERE p.pontuacao > 0
      AND NOT EXISTS (
          SELECT 1 FROM leitura l WHERE l.leitor_id = :leitor AND l.obra_id = p.candidata
      )
    ORDER BY p.pontuacao DESC, o.popularidade DESC, o.id
    LIMIT :limite
    """
)


def para_voce(conn: Connection, leitor_id: uuid.UUID, limite: int | None = None) -> ParaVoce:
    """As Sugestões do Leitor, da maior pontuação para a menor, cada uma com o Motivo.

    Com menos Notas que `config.min_notas_para_sugerir`, não calcula (a UI pede mais Notas).
    """
    cfg = config()
    notas = conn.execute(
        text("SELECT count(*) FROM leitura WHERE leitor_id = :l AND nota IS NOT NULL"),
        {"l": leitor_id},
    ).scalar_one()
    if notas < cfg.min_notas_para_sugerir:
        return ParaVoce([], notas, cfg.min_notas_para_sugerir)
    execucoes = tuple(
        conn.execute(text("SELECT id FROM execucao_modelo WHERE ativa ORDER BY id")).scalars()
    )
    linhas = conn.execute(
        _CONSULTA,
        {
            "leitor": leitor_id,
            "notas": list(PESO_DA_NOTA),
            "pesos": list(PESO_DA_NOTA.values()),
            "alfa": cfg.alfa,
            "beta": cfg.beta_popularidade,
            "limite": limite or cfg.max_sugestoes,
        },
    )
    sugestoes = [
        Sugestao(
            obra_id=r.id,
            titulo_exibicao=r.titulo_exibicao,
            autores=tuple(r.autores),
            capa_url=r.capa_url,
            ano=r.ano_original,
            pontuacao=float(r.pontuacao),
            motivo_obra_id=r.motivo,
            motivo_titulo=r.motivo_titulo,
            motivo_nota=r.motivo_nota,
        )
        for r in linhas
    ]
    return ParaVoce(sugestoes, notas, cfg.min_notas_para_sugerir, execucoes)
