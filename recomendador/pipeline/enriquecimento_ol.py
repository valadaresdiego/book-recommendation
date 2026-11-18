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
from collections.abc import Iterable, Iterator, Set
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import Connection, text

from recomendador.catalogo.fontes.open_library import assuntos as assuntos_ol
from recomendador.catalogo.fontes.open_library import texto_descricao
from recomendador.catalogo.isbn import normalizar_isbn
from recomendador.catalogo.texto import normalizar, palavras_da_busca

log = logging.getLogger(__name__)

COBERTURA_MINIMA_DESCRICAO = 0.70
_PROGRESSO_A_CADA = 5_000_000
_PALAVRA_PARECIDA = 0.8  # semelhança mínima (difflib) para duas palavras contarem como iguais

_RE_ISBNS = re.compile(r'"isbn_1[03]"\s*:\s*\[([^\]]*)\]')
_RE_ITEM = re.compile(r'"([^"]*)"')
_RE_WORK = re.compile(r'"works"\s*:\s*\[\s*\{\s*"key"\s*:\s*"(/works/[^"]+)"')
_RE_ANO = re.compile(r"\b(\d{4})\b")
_RE_TITULO = re.compile(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"')
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
    trocadas_por_irma: int = 0
    trocadas_por_errada: int = 0
    descartadas: int = 0
    achadas: int = 0

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


@dataclass(frozen=True)
class ObraDaBase:
    """O que a conferência das works precisa saber de uma Obra da Base de coleitura."""

    id: int
    titulos: frozenset[str]  # `titulo` e `titulo_original`, normalizados
    autor: str | None  # o primeiro autor, normalizado
    # O trecho antes dos dois-pontos, que na Open Library costuma ir para `subtitle`.
    curtos: frozenset[str] = frozenset()

    @classmethod
    def de(
        cls, id: int, titulo: str, titulo_original: str | None, autores: list[str] | None
    ) -> "ObraDaBase":
        brutos = [t for t in (titulo, titulo_original) if t]
        titulos = {normalizar(t) for t in brutos}
        curtos = {normalizar(t.split(":")[0]) for t in brutos if ":" in t}
        autor = normalizar(autores[0]) if autores else ""
        return cls(id, frozenset(titulos - {""}), autor or None, frozenset(curtos - {""}))

    @property
    def palavras(self) -> frozenset[str]:
        return frozenset(p for t in self.titulos for p in palavras_da_busca(t))


@dataclass(frozen=True)
class Work:
    """Título e autores de uma work do dump."""

    titulos: frozenset[str]  # normalizados; com subtítulo, só "título subtítulo"
    autores: frozenset[str]  # chaves /authors/...

    @classmethod
    def de(cls, dados: dict) -> "Work":
        titulo = str(dados.get("title") or "")
        subtitulo = str(dados.get("subtitle") or "")
        completo = normalizar(f"{titulo} {subtitulo}")
        titulos = {completo} if subtitulo.strip() else {normalizar(titulo)}
        autores = set()
        for a in dados.get("authors") or []:
            autor = a.get("author") if isinstance(a, dict) else None
            chave = autor.get("key") if isinstance(autor, dict) else autor
            if isinstance(chave, str) and chave.startswith("/authors/"):
                autores.add(chave)
        return cls(frozenset(t for t in titulos if t), frozenset(autores))

    @property
    def palavras(self) -> frozenset[str]:
        return frozenset(p for t in self.titulos for p in palavras_da_busca(t))


def _titulos_da_linha(linha: str) -> Iterator[str]:
    for bruto in _RE_TITULO.findall(linha):
        if "\\" in bruto:
            try:
                bruto = json.loads(f'"{bruto}"')
            except json.JSONDecodeError:
                continue
        yield normalizar(bruto)


def _ler_works(
    works: Path, votadas: Set[str], obras: Iterable[ObraDaBase], works_ocupados: Set[str]
) -> tuple[dict[str, Work], dict[int, set[str]]]:
    """Passada 2: título e autores das works votadas e das de mesmo título de alguma Obra.

    Devolve as works lidas e, por Obra, as works cujo título casa com o dela.
    """
    obras_por_titulo: dict[str, list[int]] = {}
    filtro: set[str] = set()  # para só ler como JSON as linhas que podem casar
    for obra in obras:
        filtro |= obra.titulos | obra.curtos
        for t in obra.titulos:
            obras_por_titulo.setdefault(t, []).append(obra.id)
    lidas: dict[str, Work] = {}
    mesmo_titulo: dict[int, set[str]] = {}
    for linha in _linhas(works):
        partes = linha.split("\t", 2)
        if len(partes) < 2 or partes[1] in works_ocupados:
            continue
        chave = partes[1]
        if chave not in votadas and not any(t in filtro for t in _titulos_da_linha(linha)):
            continue
        if (dados := _json(linha)) is None:
            continue
        work = Work.de(dados)
        obras_da_work = {o for t in work.titulos for o in obras_por_titulo.get(t, ())}
        if chave in votadas or obras_da_work:
            lidas[chave] = work
        for obra_id in obras_da_work:
            mesmo_titulo.setdefault(obra_id, set()).add(chave)
    return lidas, mesmo_titulo


def chaves_de_autor(
    obras: Iterable[ObraDaBase], votada: dict[int, str], works: dict[str, Work]
) -> dict[str, frozenset[str]]:
    """As chaves de autor da OL de cada autor, aprendidas das Obras cuja work votada tem o
    mesmo título que elas (a Open Library tem vários registros para o mesmo autor)."""
    chaves: dict[str, set[str]] = {}
    for obra in obras:
        work = works.get(votada.get(obra.id, ""))
        if obra.autor and work and obra.titulos & work.titulos:
            chaves.setdefault(obra.autor, set()).update(work.autores)
    return {autor: frozenset(c) for autor, c in chaves.items()}


@dataclass(frozen=True)
class Conferencia:
    """O resultado da conferência das works votadas (SPEC §6.2)."""

    work_por_obra: dict[int, str]
    trocadas_por_irma: int  # havia outra work de mesmo título e autor com mais Edições
    trocadas_por_errada: int  # a votada era de outra Obra e havia uma de mesmo título e autor
    descartadas: int  # a votada era de outra Obra, de outro autor, e não havia substituta
    achadas: int  # Obra sem work votada que ganhou uma pelo título e autor


def conferir_works(
    obras: Iterable[ObraDaBase],
    votada: dict[int, str],
    works: dict[str, Work],
    mesmo_titulo: dict[int, set[str]],
    edicoes: Counter[str],
) -> Conferencia:
    """A work final de cada Obra, entre a votada pelos ISBNs e as de mesmo título e autor.

    - As candidatas de uma Obra são as works de título igual ao dela e com uma chave de
      autor em comum com as Obras do mesmo autor (`chaves_de_autor`).
    - Uma votada cujo título não tem nenhuma palavra em comum com o da Obra é de outra
      Obra (o ISBN caiu na work errada na Open Library, ou numa de outro livro do mesmo
      autor). Ela sai da disputa se houver candidata, ou se for de outro autor.
    - Vence a work com mais Edições no dump; no empate, a votada e depois a menor chave.
    - Uma work fica com uma Obra só: a que a escolheu como votada primeiro, depois a de
      menor id.
    """
    obras = list(obras)
    chaves = chaves_de_autor(obras, votada, works)
    opcoes: dict[int, list[str]] = {}
    errada: set[int] = set()
    for obra in obras:
        do_autor = chaves.get(obra.autor or "", frozenset())
        candidatas = {w for w in mesmo_titulo.get(obra.id, ()) if works[w].autores & do_autor}
        v = votada.get(obra.id)
        if v is not None and _errada(obra, works.get(v), do_autor, bool(candidatas)):
            errada.add(obra.id)
            v = None
        if v is not None:
            candidatas.add(v)
        opcoes[obra.id] = sorted(candidatas, key=lambda w: (-edicoes[w], w != v, w))

    primeiro = sorted(opcoes, key=lambda o: (not opcoes[o] or opcoes[o][0] != votada.get(o), o))
    tomadas: set[str] = set()
    final: dict[int, str] = {}
    for obra_id in primeiro:
        if w := next((w for w in opcoes[obra_id] if w not in tomadas), None):
            final[obra_id] = w
            tomadas.add(w)

    contagem: Counter[str] = Counter()
    for obra_id in opcoes:
        v, f = votada.get(obra_id), final.get(obra_id)
        if v is None and f is not None:
            contagem["achadas"] += 1
        elif v is not None and f is None and obra_id in errada:
            contagem["descartadas"] += 1
        elif v is not None and f is not None and f != v:
            contagem["trocadas_por_errada" if obra_id in errada else "trocadas_por_irma"] += 1
    return Conferencia(final, **{k: contagem[k] for k in _CATEGORIAS})


_CATEGORIAS = ("trocadas_por_irma", "trocadas_por_errada", "descartadas", "achadas")


def _errada(
    obra: ObraDaBase, work: Work | None, do_autor: frozenset[str], ha_candidata: bool
) -> bool:
    # Sem palavras comparáveis (título em cirílico, por exemplo), não dá para dizer.
    if work is None or not do_autor or not work.palavras:
        return False
    if _palavra_em_comum(obra.palavras, work.palavras):
        return False
    return ha_candidata or not (work.autores & do_autor)


def _palavra_em_comum(a: frozenset[str], b: frozenset[str]) -> bool:
    """Uma palavra igual ou quase igual nos dois títulos ("Kaleidscope", "Der Kardinal im
    Kreml"), para um erro de digitação ou um título em outra língua não parecer outra Obra."""
    if a & b:
        return True
    return any(
        min(len(x), len(y)) >= 4 and SequenceMatcher(None, x, y).ratio() >= _PALAVRA_PARECIDA
        for x in a
        for y in b
    )


def _ano(publish_date: object) -> int:
    anos = _RE_ANO.findall(str(publish_date or ""))
    return int(anos[-1]) if anos else -1


@dataclass
class _EdicoesDaWork:
    quantas: int = 0
    isbns: set[str] = field(default_factory=set)
    titulo_pt: tuple[int, int, str] | None = None


def _coletar_edicoes(editions: Path, works: Set[str]) -> dict[str, _EdicoesDaWork]:
    """Passada 3: por work, quantas Edições, todos os ISBNs e o título pt mais recente."""
    por_work: dict[str, _EdicoesDaWork] = {}
    for linha in _linhas(editions):
        m = _RE_WORK.search(linha)
        if not m or m.group(1) not in works or (dados := _json(linha)) is None:
            continue
        e = por_work.setdefault(m.group(1), _EdicoesDaWork())
        e.quantas += 1
        e.isbns |= _isbns_da_edicao(dados)
        titulo = (dados.get("title") or "").strip()
        if titulo and (portugues := _em_portugues(dados)):
            candidato = (portugues, _ano(dados.get("publish_date")), titulo)
            if e.titulo_pt is None or candidato > e.titulo_pt:
                e.titulo_pt = candidato
    return por_work


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


def _coletar_works(works: Path, chaves: Set[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Passada 4: descrição e assuntos das works escolhidas (e das anteriores)."""
    descricoes: dict[str, str] = {}
    assuntos: dict[str, list[str]] = {}
    for linha in _linhas(works):
        partes = linha.split("\t", 2)
        if len(partes) < 2 or partes[1] not in chaves or (dados := _json(linha)) is None:
            continue
        if d := texto_descricao(dados.get("description")):
            descricoes[partes[1]] = d
        if a := assuntos_ol(dados.get("subjects")):
            assuntos[partes[1]] = a
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
    obras = [
        ObraDaBase.de(*linha)
        for linha in conn.execute(
            text("SELECT id, titulo, titulo_original, autores FROM obra WHERE origem = 'base'")
        )
    ]
    anterior = dict(
        conn.execute(
            text("SELECT id, ol_work_key FROM obra WHERE origem = 'base' AND ol_work_key <> ''")
        ).all()
    )

    log.info("Passada 1/4 (%s): works das %d ISBNs conhecidos", editions.name, len(obra_por_isbn))
    votada = escolher_works(_votar_works(editions, obra_por_isbn), works_ocupados)

    log.info("Passada 2/4 (%s): títulos e autores das works", works.name)
    lidas, mesmo_titulo = _ler_works(works, set(votada.values()), obras, works_ocupados)

    log.info("Passada 3/4 (%s): Edições, ISBNs e títulos em português", editions.name)
    edicoes = _coletar_edicoes(editions, set(lidas) | set(votada.values()))
    conferencia = conferir_works(
        obras, votada, lidas, mesmo_titulo, Counter({w: e.quantas for w, e in edicoes.items()})
    )
    work_por_obra = conferencia.work_por_obra

    log.info("Passada 4/4 (%s): descrições e assuntos", works.name)
    descricoes, assuntos = _coletar_works(works, {*work_por_obra.values(), *anterior.values()})

    isbns = [(i, o) for o, w in work_por_obra.items() for i in edicoes.get(w, _VAZIA).isbns]
    titulo_pt = {
        o: e.titulo_pt[2] for o, w in work_por_obra.items() if (e := edicoes.get(w)) and e.titulo_pt
    }
    # Uma descrição que veio da work anterior da Obra sai junto com ela.
    descricao_velha = {
        o: d for o, w in anterior.items() if work_por_obra.get(o) != w and (d := descricoes.get(w))
    }
    _gravar(
        conn,
        work_por_obra,
        isbns,
        titulo_pt,
        {o: descricoes[w] for o, w in work_por_obra.items() if w in descricoes},
        {o: assuntos[w] for o, w in work_por_obra.items() if w in assuntos},
        descricao_velha,
    )
    novos = len({i for i, _ in isbns} - set(obra_por_isbn))
    resumo = _resumo(conn, len(titulo_pt), novos, conferencia)
    _registrar(resumo)
    return resumo


_VAZIA = _EdicoesDaWork()


def _gravar(
    conn: Connection,
    work_por_obra: dict[int, str],
    isbns: list[tuple[str, int]],
    titulo_pt: dict[int, str],
    descricoes: dict[int, str],
    assuntos: dict[int, list[str]],
    descricao_velha: dict[int, str],
) -> None:
    # Limpa o que veio de uma execução anterior, para o resultado depender só do dump atual.
    conn.execute(text("UPDATE obra SET ol_work_key = NULL WHERE origem = 'base'"))
    if descricao_velha:
        conn.execute(
            text("UPDATE obra SET descricao = NULL WHERE id = :o AND descricao = :d"),
            [{"o": o, "d": d} for o, d in descricao_velha.items()],
        )
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


def _resumo(
    conn: Connection, com_titulo_pt: int, isbns_novos: int, c: Conferencia
) -> ResumoEnriquecimento:
    obras, com_work, com_descricao = conn.execute(_CONTAGENS).one()
    return ResumoEnriquecimento(
        obras=obras,
        com_work=com_work,
        com_descricao=com_descricao,
        com_titulo_pt=com_titulo_pt,
        isbns_novos=isbns_novos,
        **{k: getattr(c, k) for k in _CATEGORIAS},
    )


def _registrar(r: ResumoEnriquecimento) -> None:
    log.info("Obras da Base de coleitura: %d", r.obras)
    log.info("  com ol_work_key:        %6d (%.1f %%)", r.com_work, r.pct(r.com_work))
    log.info("  com descrição:          %6d (%.1f %%)", r.com_descricao, r.pct(r.com_descricao))
    log.info("  com título em português:%6d (%.1f %%)", r.com_titulo_pt, r.pct(r.com_titulo_pt))
    log.info("  ISBNs novos em obra_isbn: %d", r.isbns_novos)
    log.info("Conferência das works votadas pelos ISBNs:")
    log.info("  trocadas por uma de mesmo título e autor com mais Edições: %d", r.trocadas_por_irma)
    log.info(
        "  trocadas por serem de outra Obra (título sem palavra em comum): %d",
        r.trocadas_por_errada,
    )
    log.info("  descartadas (outra Obra, de outro autor, sem substituta): %d", r.descartadas)
    log.info("  achadas pelo título e autor para Obras sem work votada: %d", r.achadas)
    if r.obras and r.com_descricao / r.obras < COBERTURA_MINIMA_DESCRICAO:
        log.warning("Cobertura de descrição abaixo de %.0f %%", 100 * COBERTURA_MINIMA_DESCRICAO)
