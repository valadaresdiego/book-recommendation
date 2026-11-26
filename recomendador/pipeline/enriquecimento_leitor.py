"""Enriquecimento das Obras do Leitor pela API da Open Library (passo 2 do `atualizar`, SPEC §10).

As Obras criadas na resolução já nascem enriquecidas quando a Open Library respondeu. Ficam
pendentes as do cadastro manual e as criadas com a Open Library fora do ar. Este passo
pega até 100 delas por execução, a 1 req/s (o limitador está no cliente).
"""

import logging
import time
from dataclasses import dataclass

from sqlalchemy import Connection, text

from recomendador.catalogo.fontes import FonteIndisponivel
from recomendador.catalogo.fontes.open_library import ObraOL, OpenLibrary

log = logging.getLogger(__name__)

MAX_POR_EXECUCAO = 100


@dataclass(frozen=True)
class ResumoEnriquecimentoLeitor:
    processadas: int  # marcadas com enriquecida_em, achando ou não a work
    com_work: int
    pendentes: int  # continuam sem enriquecida_em (OL fora do ar ou prazo esgotado)


def _work_pelos_isbns(ol: OpenLibrary, isbns: list[str]) -> str | None:
    for isbn in isbns:
        if (edicao := ol.edicao_por_isbn(isbn)) and edicao.works:
            return edicao.works[0]
    return None


def _gravar(conn: Connection, obra_id: int, work: ObraOL | None) -> None:
    if work is not None:
        conn.execute(
            text(
                """
                UPDATE obra SET
                    ol_work_key = CASE WHEN NOT EXISTS (
                        SELECT 1 FROM obra outra
                        WHERE outra.ol_work_key = :work AND outra.id <> :o
                    ) THEN :work ELSE ol_work_key END,
                    descricao = coalesce(descricao, :descricao),
                    capa_url = coalesce(capa_url, :capa),
                    ano_original = coalesce(ano_original, :ano)
                WHERE id = :o
                """
            ),
            {
                "o": obra_id,
                "work": work.chave,
                "descricao": work.descricao,
                "capa": work.capa_url,
                "ano": work.ano,
            },
        )
        if work.assuntos:
            conn.execute(
                text(
                    "INSERT INTO obra_tag (obra_id, tag, contagem) VALUES (:o, :t, 0) "
                    "ON CONFLICT DO NOTHING"
                ),
                [{"o": obra_id, "t": t} for t in work.assuntos],
            )
    conn.execute(text("UPDATE obra SET enriquecida_em = now() WHERE id = :o"), {"o": obra_id})


def enriquecer_obras_do_leitor(
    conn: Connection,
    ol: OpenLibrary,
    limite: int = MAX_POR_EXECUCAO,
    prazo: float | None = None,
) -> ResumoEnriquecimentoLeitor:
    """Enriquece até `limite` Obras `origem='leitor'` sem `enriquecida_em`.

    `prazo` é um instante de `time.monotonic()` depois do qual não começa outra Obra. Se a
    Open Library cair no meio, para e deixa o resto pendente para a próxima abertura.
    """
    obras = conn.execute(
        text(
            """
            SELECT o.id, o.ol_work_key,
                   array_remove(array_agg(i.isbn13 ORDER BY i.isbn13), NULL) AS isbns
            FROM obra o LEFT JOIN obra_isbn i ON i.obra_id = o.id
            WHERE o.origem = 'leitor' AND o.enriquecida_em IS NULL
            GROUP BY o.id ORDER BY o.id LIMIT :n
            """
        ),
        {"n": limite},
    ).all()
    processadas = com_work = 0
    for obra in obras:
        if prazo is not None and time.monotonic() > prazo:
            log.warning("Prazo do atualizar esgotado; Obras do Leitor ficam para a próxima")
            break
        try:
            chave = obra.ol_work_key or _work_pelos_isbns(ol, list(obra.isbns))
            work = ol.obra(chave) if chave else None
        except FonteIndisponivel as e:
            log.warning("Open Library indisponível; Obras do Leitor ficam para a próxima: %s", e)
            break
        _gravar(conn, obra.id, work)
        processadas += 1
        com_work += work is not None
    pendentes = len(obras) - processadas
    if obras:
        log.info(
            "Obras do Leitor enriquecidas: %d (%d com work da Open Library), %d pendentes",
            processadas,
            com_work,
            pendentes,
        )
    return ResumoEnriquecimentoLeitor(processadas, com_work, pendentes)
