"""'Para você' (R4, SPEC §8.5): uma consulta SQL sobre as execuções ativas.

A similaridade de cada execução é dividida pela escala dela (`parametros.escala`, a média
dos seus Vizinhos) antes da mistura por α (ADR 0007), e a soma das parcelas é multiplicada
por (1 + popularidade)^β (ADR 0006).

A conta é a mesma de `recomendacao.pontuacao` (a da avaliação offline, §9); um teste
confere as duas.

Fase 4 (§8.6): as Dispensas (R7) e a lista Quero ler (R8) saem das candidatas; os filtros
por Gênero e por Edição em português (R10) entram depois da pontuação, sem mudá-la; e cada
Sugestão traz os 3 maiores Contribuintes (R11).

Fase 6 (§8.8, ADR 0009): a aba "Tecnologia" usa a mesma consulta só com a execução
`tecnico` (α = 1, β = 0). A lista geral usa só as de conteúdo e de Coleitura e nunca traz
uma Obra técnica da Open Library.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

from recomendador.config import PESO_DA_NOTA, config

CONTRIBUINTES = 3  # do Motivo detalhado (R11)


@dataclass(frozen=True)
class Contribuinte:
    """Uma Leitura de Nota alta que somou pontos à Sugestão (R11)."""

    obra_id: int
    titulo_exibicao: str
    nota: int
    participacao: float  # parcela ÷ soma das parcelas positivas da Sugestão (0 a 1)


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
    # O Motivo detalhado: os maiores Contribuintes, o primeiro é o Motivo.
    contribuintes: tuple[Contribuinte, ...] = ()


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
                   CASE e.tipo WHEN 'conteudo' THEN :alfa WHEN 'coleitura' THEN 1 - :alfa
                               ELSE 1 END
                   * v.similaridade / coalesce((e.parametros ->> 'escala')::float8, 1)
               ) AS parcela
        FROM leituras r
        JOIN vizinho v ON v.obra_id = r.obra_id
        JOIN execucao_modelo e
          ON e.id = v.execucao_id AND e.ativa AND e.tipo::text = ANY(CAST(:tipos AS text[]))
        GROUP BY v.vizinho_id, r.obra_id, r.nota, r.peso
    ),
    pontos AS (
        SELECT p.candidata,
               sum(p.parcela) * power(1 + max(o.popularidade), :beta) AS pontuacao
        FROM parcelas p JOIN obra o ON o.id = p.candidata
        GROUP BY p.candidata
    ),
    positivas AS (
        SELECT candidata, motivo, nota, parcela,
               row_number() OVER (PARTITION BY candidata ORDER BY parcela DESC, motivo) AS ordem,
               sum(parcela) OVER (PARTITION BY candidata) AS total
        FROM parcelas WHERE parcela > 0 AND peso > 0
    ),
    contribuintes AS (
        SELECT c.candidata,
               array_agg(c.motivo ORDER BY c.ordem) AS obras,
               array_agg(mo.titulo_exibicao ORDER BY c.ordem) AS titulos,
               array_agg(c.nota ORDER BY c.ordem) AS notas,
               array_agg(c.parcela / c.total ORDER BY c.ordem) AS participacoes
        FROM positivas c JOIN obra mo ON mo.id = c.motivo
        WHERE c.ordem <= :contribuintes
        GROUP BY c.candidata
    )
    SELECT o.id, o.titulo_exibicao, o.autores, o.capa_url, o.ano_original, p.pontuacao,
           c.obras, c.titulos, c.notas, c.participacoes
    FROM pontos p
    JOIN contribuintes c USING (candidata)
    JOIN obra o ON o.id = p.candidata
    WHERE p.pontuacao > 0
      AND NOT EXISTS (
          SELECT 1 FROM leitura l WHERE l.leitor_id = :leitor AND l.obra_id = p.candidata
      )
      AND NOT EXISTS (
          SELECT 1 FROM dispensa d WHERE d.leitor_id = :leitor AND d.obra_id = p.candidata
      )
      AND NOT EXISTS (
          SELECT 1 FROM quero_ler q WHERE q.leitor_id = :leitor AND q.obra_id = p.candidata
      )
      AND NOT EXISTS (
          SELECT 1 FROM estou_lendo el WHERE el.leitor_id = :leitor AND el.obra_id = p.candidata
      )
      -- R10: os filtros vêm depois da pontuação e antes do limite.
      AND (cardinality(CAST(:generos AS text[])) = 0 OR EXISTS (
          SELECT 1 FROM obra_genero og JOIN genero g ON g.id = og.genero_id
          WHERE og.obra_id = p.candidata AND g.slug = ANY(CAST(:generos AS text[]))
      ))
      AND (NOT :so_edicao_pt OR o.tem_edicao_pt)
      AND (:tecnologia OR o.origem <> 'open_library')
    ORDER BY p.pontuacao DESC, o.popularidade DESC, o.id
    LIMIT :limite
    """
)


def para_voce(
    conn: Connection,
    leitor_id: uuid.UUID,
    limite: int | None = None,
    *,
    generos: Sequence[str] = (),
    so_edicao_pt: bool = False,
) -> ParaVoce:
    """As Sugestões do Leitor, da maior pontuação para a menor, cada uma com o Motivo e os
    Contribuintes.

    `generos` (slugs) deixa só as Obras de algum desses Gêneros, e `so_edicao_pt` só as
    com Edição em português (R10). Os filtros não mudam a pontuação nem a ordem.

    Com menos Notas que `config.min_notas_para_sugerir`, não calcula (a UI pede mais Notas).
    """
    cfg = config()
    return _sugestoes(
        conn,
        leitor_id,
        limite,
        tipos=TIPOS_DA_LISTA_GERAL,
        beta=cfg.beta_popularidade,
        generos=generos,
        so_edicao_pt=so_edicao_pt,
        tecnologia=False,
    )


def para_voce_tecnologia(
    conn: Connection, leitor_id: uuid.UUID, limite: int | None = None, *, so_edicao_pt: bool = False
) -> ParaVoce:
    """As Sugestões técnicas (aba "Tecnologia", R14, SPEC §8.8): a consulta de `para_voce`
    só com a execução `tecnico`, sem popularidade (β = 0) e sem filtro de Gênero. Qualquer
    Leitura com Nota pode ser Contribuinte."""
    return _sugestoes(
        conn,
        leitor_id,
        limite,
        tipos=("tecnico",),
        beta=0.0,
        generos=(),
        so_edicao_pt=so_edicao_pt,
        tecnologia=True,
    )


TIPOS_DA_LISTA_GERAL = ("conteudo", "coleitura")


def _sugestoes(
    conn: Connection,
    leitor_id: uuid.UUID,
    limite: int | None,
    *,
    tipos: Sequence[str],
    beta: float,
    generos: Sequence[str],
    so_edicao_pt: bool,
    tecnologia: bool,
) -> ParaVoce:
    cfg = config()
    notas = conn.execute(
        text("SELECT count(*) FROM leitura WHERE leitor_id = :l AND nota IS NOT NULL"),
        {"l": leitor_id},
    ).scalar_one()
    if notas < cfg.min_notas_para_sugerir:
        return ParaVoce([], notas, cfg.min_notas_para_sugerir)
    execucoes = tuple(
        conn.execute(
            text(
                "SELECT id FROM execucao_modelo "
                "WHERE ativa AND tipo::text = ANY(CAST(:t AS text[])) ORDER BY id"
            ),
            {"t": list(tipos)},
        ).scalars()
    )
    linhas = conn.execute(
        _CONSULTA,
        {
            "leitor": leitor_id,
            "notas": list(PESO_DA_NOTA),
            "pesos": list(PESO_DA_NOTA.values()),
            "tipos": list(tipos),
            "alfa": cfg.alfa,
            "beta": beta,
            "limite": limite or cfg.max_sugestoes,
            "contribuintes": CONTRIBUINTES,
            "generos": list(generos),
            "so_edicao_pt": so_edicao_pt,
            "tecnologia": tecnologia,
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
            motivo_obra_id=r.obras[0],
            motivo_titulo=r.titulos[0],
            motivo_nota=r.notas[0],
            contribuintes=tuple(
                Contribuinte(o, t, n, float(p))
                for o, t, n, p in zip(r.obras, r.titulos, r.notas, r.participacoes, strict=True)
            ),
        )
        for r in linhas
    ]
    return ParaVoce(sugestoes, notas, cfg.min_notas_para_sugerir, execucoes)
