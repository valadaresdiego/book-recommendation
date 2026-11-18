"""Enriquecimento das Obras da Base de coleitura pelos dumps da Open Library (SPEC §6.2).

Os dumps são TSV comprimidos (tipo, chave, revisão, data, JSON), com dezenas de milhões de
linhas. Tudo roda em streaming, e cada linha passa antes por um filtro de regex barato:
só as linhas que interessam são lidas como JSON.
"""

import gzip
import json
import logging
import re
from collections import Counter
from collections.abc import Iterator, Set
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, text

from recomendador.catalogo.fontes.open_library import assuntos as assuntos_ol
from recomendador.catalogo.fontes.open_library import texto_descricao
from recomendador.catalogo.isbn import normalizar_isbn

log = logging.getLogger(__name__)

COBERTURA_MINIMA_DESCRICAO = 0.70
_PROGRESSO_A_CADA = 5_000_000

_RE_ISBNS = re.compile(r'"isbn_1[03]"\s*:\s*\[([^\]]*)\]')
_RE_ITEM = re.compile(r'"([^"]*)"')
_RE_WORK = re.compile(r'"works"\s*:\s*\[\s*\{\s*"key"\s*:\s*"(/works/[^"]+)"')
_RE_ANO = re.compile(r"\b(\d{4})\b")
_PORTUGUES = "/languages/por"
_PREFIXOS_BR = ("97885", "97865")  # ISBNs da Agência Brasileira


class DumpAusente(FileNotFoundError):
    pass


@dataclass(frozen=True)
class ResumoEnriquecimento:
    obras: int
    com_work: int
    com_descricao: int
    com_titulo_pt: int
    isbns_novos: int

    def pct(self, n: int) -> float:
        return 100 * n / self.obras if self.obras else 0.0


def localizar_dump(pasta: Path, tipo: str) -> Path:
    """O dump mais recente de `tipo` (`editions`, `works`) em `pasta`."""
    candidatos = sorted(pasta.glob(f"ol_dump_{tipo}_*.txt.gz")) + sorted(
        pasta.glob(f"ol_dump_{tipo}_*.txt")
    )
    if not candidatos:
        raise DumpAusente(
            f"Nenhum dump de {tipo} em {pasta} (esperado ol_dump_{tipo}_*.txt.gz). "
            "Rode `enriquecer-ol --baixar` ou baixe de https://openlibrary.org/developers/dumps"
        )
    return candidatos[-1]


def _linhas(caminho: Path) -> Iterator[str]:
    abrir = gzip.open if caminho.suffix == ".gz" else open
    with abrir(caminho, "rt", encoding="utf-8", errors="replace") as f:
        for i, linha in enumerate(f, 1):
            if i % _PROGRESSO_A_CADA == 0:
                log.info("  %s: %d milhões de linhas", caminho.name, i // 1_000_000)
            yield linha


def _json(linha: str) -> dict | None:
    partes = linha.rstrip("\n").split("\t", 4)
    if len(partes) < 5:
        return None
    try:
        return json.loads(partes[4])
    except json.JSONDecodeError:
        return None


def _isbns_da_edicao(dados: dict) -> set[str]:
    brutos = list(dados.get("isbn_13") or []) + list(dados.get("isbn_10") or [])
    return {n for b in brutos if isinstance(b, str) and (n := normalizar_isbn(b))}


def _work_da_edicao(dados: dict) -> str | None:
    works = dados.get("works") or []
    if works and isinstance(works[0], dict):
        return works[0].get("key")
    return None


def _votar_works(editions: Path, obra_por_isbn: dict[str, int]) -> Counter[tuple[int, str]]:
    """Passada 1: cada Edição com ISBN conhecido vota no work dela para a Obra."""
    votos: Counter[tuple[int, str]] = Counter()
    for linha in _linhas(editions):
        candidatos = {
            n
            for grupo in _RE_ISBNS.findall(linha)
            for item in _RE_ITEM.findall(grupo)
            if (n := normalizar_isbn(item))
        }
        obras = {obra_por_isbn[i] for i in candidatos if i in obra_por_isbn}
        if not obras or (dados := _json(linha)) is None or not (work := _work_da_edicao(dados)):
            continue
        for obra_id in obras:
            votos[(obra_id, work)] += 1
    return votos


def escolher_works(
    votos: Counter[tuple[int, str]], works_ocupados: Set[str] = frozenset()
) -> dict[int, str]:
    """Um work por Obra (o mais votado) e uma Obra por work (a que deu mais votos a ele).

    Empates são decididos pela menor chave, para o resultado não depender da ordem do dump.
    """
    melhor: dict[int, tuple[int, str]] = {}
    for (obra_id, work), n in sorted(votos.items()):
        if work not in works_ocupados and n > melhor.get(obra_id, (0, ""))[0]:
            melhor[obra_id] = (n, work)
    dono: dict[str, tuple[int, int]] = {}
    for obra_id, (n, work) in sorted(melhor.items()):
        if n > dono.get(work, (0, 0))[0]:
            dono[work] = (n, obra_id)
    return {obra_id: work for work, (_, obra_id) in dono.items()}


def _ano(publish_date: object) -> int:
    anos = _RE_ANO.findall(str(publish_date or ""))
    return int(anos[-1]) if anos else -1


def _coletar_edicoes(
    editions: Path, obra_por_work: dict[str, int]
) -> tuple[list[tuple[str, int]], dict[int, str]]:
    """Passada 2: todos os ISBNs das works escolhidas e o título pt mais recente de cada Obra."""
    isbns: list[tuple[str, int]] = []
    titulo_pt: dict[int, tuple[int, int, str]] = {}
    for linha in _linhas(editions):
        m = _RE_WORK.search(linha)
        if not m or m.group(1) not in obra_por_work or (dados := _json(linha)) is None:
            continue
        obra_id = obra_por_work[m.group(1)]
        isbns.extend((i, obra_id) for i in _isbns_da_edicao(dados))
        titulo = (dados.get("title") or "").strip()
        if titulo and (portugues := _em_portugues(dados)):
            candidato = (portugues, _ano(dados.get("publish_date")), titulo)
            if obra_id not in titulo_pt or candidato > titulo_pt[obra_id]:
                titulo_pt[obra_id] = candidato
    return isbns, {o: t for o, (_, _, t) in titulo_pt.items()}


def _em_portugues(dados: dict) -> int:
    """2 se a Edição declara português; 1 se não declara idioma e tem ISBN brasileiro; 0 se não.

    A reserva pelo ISBN (prefixos 978-85 e 978-65) cobre as Edições brasileiras que a
    Open Library cadastrou sem `languages`. Uma Edição que declara português vence sempre.
    """
    idiomas = {i.get("key") for i in dados.get("languages") or [] if isinstance(i, dict)}
    if _PORTUGUES in idiomas:
        return 2
    if not idiomas and any(i.startswith(_PREFIXOS_BR) for i in _isbns_da_edicao(dados)):
        return 1
    return 0


def _coletar_works(
    works: Path, obra_por_work: dict[str, int]
) -> tuple[dict[int, str], dict[int, list[str]]]:
    """Passada 3: descrição e assuntos das works escolhidas."""
    descricoes: dict[int, str] = {}
    assuntos: dict[int, list[str]] = {}
    for linha in _linhas(works):
        partes = linha.split("\t", 2)
        if len(partes) < 2 or partes[1] not in obra_por_work or (dados := _json(linha)) is None:
            continue
        obra_id = obra_por_work[partes[1]]
        if d := texto_descricao(dados.get("description")):
            descricoes[obra_id] = d
        if a := assuntos_ol(dados.get("subjects")):
            assuntos[obra_id] = a
    return descricoes, assuntos


def enriquecer_ol(conn: Connection, pasta_dumps: Path) -> ResumoEnriquecimento:
    editions = localizar_dump(pasta_dumps, "editions")
    works = localizar_dump(pasta_dumps, "works")

    obra_por_isbn = dict(
        conn.execute(
            text(
                "SELECT i.isbn13, i.obra_id FROM obra_isbn i "
                "JOIN obra o ON o.id = i.obra_id WHERE o.origem = 'base'"
            )
        ).all()
    )
    works_ocupados = set(
        conn.execute(
            text("SELECT ol_work_key FROM obra WHERE origem <> 'base' AND ol_work_key IS NOT NULL")
        ).scalars()
    )

    log.info("Passada 1/3 (%s): works das %d ISBNs conhecidos", editions.name, len(obra_por_isbn))
    work_por_obra = escolher_works(_votar_works(editions, obra_por_isbn), works_ocupados)
    obra_por_work = {w: o for o, w in work_por_obra.items()}

    log.info("Passada 2/3 (%s): ISBNs e títulos em português", editions.name)
    isbns, titulo_pt = _coletar_edicoes(editions, obra_por_work)

    log.info("Passada 3/3 (%s): descrições e assuntos", works.name)
    descricoes, assuntos = _coletar_works(works, obra_por_work)

    _gravar(conn, work_por_obra, isbns, titulo_pt, descricoes, assuntos)
    novos = len({i for i, _ in isbns} - set(obra_por_isbn))
    resumo = _resumo(conn, len(titulo_pt), novos)
    _registrar(resumo)
    return resumo


def _gravar(
    conn: Connection,
    work_por_obra: dict[int, str],
    isbns: list[tuple[str, int]],
    titulo_pt: dict[int, str],
    descricoes: dict[int, str],
    assuntos: dict[int, list[str]],
) -> None:
    # Limpa o que veio de uma execução anterior, para o resultado depender só do dump atual.
    conn.execute(text("UPDATE obra SET ol_work_key = NULL WHERE origem = 'base'"))
    conn.execute(
        text(
            "DELETE FROM obra_tag t USING obra o "
            "WHERE o.id = t.obra_id AND o.origem = 'base' AND t.contagem = 0"
        )
    )
    if work_por_obra:
        conn.execute(
            text("UPDATE obra SET ol_work_key = :w WHERE id = :o"),
            [{"o": o, "w": w} for o, w in work_por_obra.items()],
        )
    if isbns:
        conn.execute(
            text("INSERT INTO obra_isbn (isbn13, obra_id) VALUES (:i, :o) ON CONFLICT DO NOTHING"),
            [{"i": i, "o": o} for i, o in dict(isbns).items()],
        )
    conn.execute(
        text("UPDATE obra SET titulo_exibicao = titulo WHERE origem = 'base'"),
    )
    if titulo_pt:
        conn.execute(
            text("UPDATE obra SET titulo_exibicao = :t WHERE id = :o"),
            [{"o": o, "t": t} for o, t in titulo_pt.items()],
        )
    if descricoes:
        conn.execute(
            text("UPDATE obra SET descricao = :d WHERE id = :o AND descricao IS NULL"),
            [{"o": o, "d": d} for o, d in descricoes.items()],
        )
    linhas_assunto = [{"o": o, "t": t} for o, lista in assuntos.items() for t in lista]
    if linhas_assunto:
        conn.execute(
            text(
                "INSERT INTO obra_tag (obra_id, tag, contagem) VALUES (:o, :t, 0) "
                "ON CONFLICT DO NOTHING"
            ),
            linhas_assunto,
        )
    conn.execute(text("UPDATE obra SET enriquecida_em = now() WHERE origem = 'base'"))


_CONTAGENS = text(
    """
    SELECT count(*),
           count(ol_work_key),
           count(descricao)
    FROM obra WHERE origem = 'base'
    """
)


def _resumo(conn: Connection, com_titulo_pt: int, isbns_novos: int) -> ResumoEnriquecimento:
    obras, com_work, com_descricao = conn.execute(_CONTAGENS).one()
    return ResumoEnriquecimento(
        obras=obras,
        com_work=com_work,
        com_descricao=com_descricao,
        com_titulo_pt=com_titulo_pt,
        isbns_novos=isbns_novos,
    )


def _registrar(r: ResumoEnriquecimento) -> None:
    log.info("Obras da Base de coleitura: %d", r.obras)
    log.info("  com ol_work_key:        %6d (%.1f %%)", r.com_work, r.pct(r.com_work))
    log.info("  com descrição:          %6d (%.1f %%)", r.com_descricao, r.pct(r.com_descricao))
    log.info("  com título em português:%6d (%.1f %%)", r.com_titulo_pt, r.pct(r.com_titulo_pt))
    log.info("  ISBNs novos em obra_isbn: %d", r.isbns_novos)
    if r.obras and r.com_descricao / r.obras < COBERTURA_MINIMA_DESCRICAO:
        log.warning("Cobertura de descrição abaixo de %.0f %%", 100 * COBERTURA_MINIMA_DESCRICAO)
