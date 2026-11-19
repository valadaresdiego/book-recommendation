"""`carregar-tecnicas`: as Obras técnicas dos dumps da Open Library (SPEC §8.8, ADR 0009).

Três passadas em streaming, como no `enriquecer-ol` (§6.2):

1. **works**: as works técnicas pelos assuntos (`catalogo/assuntos_tecnicos.yaml`) e as da
   lista curada (`catalogo/tecnicos_curados.yaml`);
2. **editions**: por work, o nº de Edições, o ano mais recente, as editoras, os ISBNs e as
   Edições em português;
3. **authors**: os nomes dos autores das works escolhidas.

Entram as works com ≥ 10 Edições, as de editora técnica (`catalogo/editoras_tecnicas.txt`)
com Edição desde 2012 e ≥ 2 Edições ou Edição desde 2018, e as da lista curada. As outras
Obras técnicas do Catálogo (Base e Leitor) continuam como estão.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import Connection, text

from recomendador.catalogo.fontes.open_library import URL_CAPA, ano_de, texto_descricao
from recomendador.catalogo.fontes.open_library import assuntos as assuntos_ol
from recomendador.catalogo.generos import SLUG_TECNOLOGIA
from recomendador.catalogo.texto import normalizar
from recomendador.pipeline.enriquecimento_ol import (
    _RE_WORK,
    _em_portugues,
    _isbns_da_edicao,
    _json,
    _linhas,
    localizar_dump,
)

log = logging.getLogger(__name__)

_CATALOGO = Path(__file__).resolve().parents[1] / "catalogo"
ARQUIVO_ASSUNTOS = _CATALOGO / "assuntos_tecnicos.yaml"
ARQUIVO_EDITORAS = _CATALOGO / "editoras_tecnicas.txt"
ARQUIVO_CURADOS = _CATALOGO / "tecnicos_curados.yaml"

# O corte do §8.8 (medido em 19/11/2026: ~4.250 works).
MIN_EDICOES = 10
ANO_EDITORA = 2012
MIN_EDICOES_EDITORA = 2
ANO_LANCAMENTO = 2018

# Filtro barato, antes do JSON: só as linhas cujos assuntos citam algum destes radicais.
_RE_RADICAIS = re.compile(
    r"program|software|comput|machine learning|artificial intelligence|data mining|database"
    r"|web site|user interface|devops",
    re.IGNORECASE,
)
_RE_ANO = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


class CuradaInvalida(ValueError):
    """Um item da lista curada não existe no dump ou não bate com o título da work."""


# --- Critério e listas ---


@dataclass(frozen=True)
class Criterio:
    iguais: frozenset[str]
    prefixos: tuple[str, ...]
    sufixos: tuple[str, ...]
    ruido_assuntos: re.Pattern
    ruido_titulos: re.Pattern

    def tecnica(self, assuntos: list[str]) -> bool:
        return any(
            a in self.iguais or a.startswith(self.prefixos) or a.endswith(self.sufixos)
            for a in assuntos
        )

    def ruido(self, titulo: str, assuntos: list[str]) -> bool:
        """Ficção, anais e séries: saem do corte (não da lista curada)."""
        return bool(self.ruido_titulos.search(titulo)) or any(
            self.ruido_assuntos.search(a) for a in assuntos
        )


def _alternativas(palavras: list[str]) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(re.escape(p) for p in palavras) + r")\b", re.IGNORECASE)


def ler_criterio(caminho: Path = ARQUIVO_ASSUNTOS) -> Criterio:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    return Criterio(
        iguais=frozenset(_limpar(a) for a in dados["iguais"]),
        prefixos=tuple(_limpar(a) for a in dados["prefixos"]),
        sufixos=tuple(_limpar(a) for a in dados["sufixos"]),
        ruido_assuntos=_alternativas(dados["ruido_assuntos"]),
        ruido_titulos=_alternativas(dados["ruido_titulos"]),
    )


def ler_editoras(caminho: Path = ARQUIVO_EDITORAS) -> re.Pattern:
    linhas = [
        linha.strip()
        for linha in caminho.read_text(encoding="utf-8").splitlines()
        if linha.strip() and not linha.lstrip().startswith("#")
    ]
    return re.compile("|".join(f"(?:{linha})" for linha in linhas), re.IGNORECASE)


@dataclass(frozen=True)
class Curada:
    work: str
    titulo: str
    autor: str
    fundir: tuple[str, ...] = ()


def ler_curados(caminho: Path = ARQUIVO_CURADOS) -> list[Curada]:
    itens = yaml.safe_load(caminho.read_text(encoding="utf-8")) or []
    curadas = [
        Curada(i["work"], i["titulo"], i["autor"], tuple(i.get("fundir") or ())) for i in itens
    ]
    chaves = [c.work for c in curadas] + [f for c in curadas for f in c.fundir]
    if repetidas := sorted({k for k in chaves if chaves.count(k) > 1}):
        raise CuradaInvalida(f"{caminho}: works repetidas na lista curada: {repetidas}")
    return curadas


def _limpar(assunto: str) -> str:
    return " ".join(assunto.split()).lower()


# --- Leitura dos dumps ---


@dataclass
class WorkLida:
    chave: str
    titulo: str
    autores: tuple[str, ...]  # chaves /authors/...
    descricao: str | None
    assuntos: list[str]
    capa: int | None
    ano: int | None  # first_publish_date


@dataclass
class EdicoesDaWork:
    quantas: int = 0
    ano_min: int | None = None
    ano_max: int | None = None
    editoras: set[str] = field(default_factory=set)
    isbns: set[str] = field(default_factory=set)
    em_portugues: bool = False
    titulo_pt: tuple[int, int, str] | None = None  # (força do português, ano, título)


def _titulo_da_work(dados: dict) -> str:
    titulo = " ".join(str(dados.get("title") or "").split())
    subtitulo = " ".join(str(dados.get("subtitle") or "").split())
    return f"{titulo}: {subtitulo}" if subtitulo else titulo


def _work_lida(dados: dict) -> WorkLida:
    autores = tuple(
        a["author"]["key"]
        for a in dados.get("authors") or []
        if isinstance(a, dict) and isinstance(a.get("author"), dict) and a["author"].get("key")
    )
    capas = [c for c in dados.get("covers") or [] if isinstance(c, int) and c > 0]
    return WorkLida(
        chave=dados["key"],
        titulo=_titulo_da_work(dados),
        autores=tuple(dict.fromkeys(autores)),
        descricao=texto_descricao(dados.get("description")),
        assuntos=assuntos_ol(dados.get("subjects")),
        capa=capas[0] if capas else None,
        ano=ano_de(dados.get("first_publish_date")),
    )


def _ler_works(
    caminho: Path, criterio: Criterio, curadas: set[str]
) -> tuple[dict[str, WorkLida], dict[str, WorkLida]]:
    """Passada 1: (works técnicas fora do ruído, works da lista curada)."""
    tecnicas: dict[str, WorkLida] = {}
    da_lista: dict[str, WorkLida] = {}
    for linha in _linhas(caminho):
        partes = linha.split("\t", 2)
        if len(partes) < 2:
            continue
        chave = partes[1]
        if chave not in curadas:
            inicio = linha.find('"subjects"')
            if inicio < 0 or not _RE_RADICAIS.search(linha, inicio, linha.find("]", inicio)):
                continue
        if (dados := _json(linha)) is None or not dados.get("key"):
            continue
        w = _work_lida(dados)
        if chave in curadas:
            da_lista[chave] = w
        elif criterio.tecnica(w.assuntos) and not criterio.ruido(w.titulo, w.assuntos):
            tecnicas[chave] = w
    return tecnicas, da_lista


def _ano_da_edicao(publish_date: object) -> int | None:
    limite = date.today().year + 1
    anos = [int(a) for a in _RE_ANO.findall(str(publish_date or "")) if int(a) <= limite]
    return max(anos) if anos else None


def _ler_edicoes(caminho: Path, works: set[str]) -> dict[str, EdicoesDaWork]:
    """Passada 2: as Edições de cada work pedida."""
    por_work: dict[str, EdicoesDaWork] = {}
    for linha in _linhas(caminho):
        m = _RE_WORK.search(linha)
        if not m or m.group(1) not in works or (dados := _json(linha)) is None:
            continue
        e = por_work.setdefault(m.group(1), EdicoesDaWork())
        e.quantas += 1
        if (ano := _ano_da_edicao(dados.get("publish_date"))) is not None:
            e.ano_min = ano if e.ano_min is None else min(e.ano_min, ano)
            e.ano_max = ano if e.ano_max is None else max(e.ano_max, ano)
        e.editoras |= {
            p.strip() for p in dados.get("publishers") or [] if isinstance(p, str) and p.strip()
        }
        e.isbns |= _isbns_da_edicao(dados)
        portugues = _em_portugues(dados)
        e.em_portugues |= portugues > 0
        titulo = " ".join(str(dados.get("title") or "").split())
        if titulo and portugues:
            candidato = (portugues, ano or -1, titulo)
            if e.titulo_pt is None or candidato > e.titulo_pt:
                e.titulo_pt = candidato
    return por_work


def _ler_autores(caminho: Path, chaves: set[str]) -> dict[str, str]:
    """Passada 3: o nome de cada autor pedido."""
    nomes: dict[str, str] = {}
    for linha in _linhas(caminho):
        partes = linha.split("\t", 2)
        if len(partes) < 2 or partes[1] not in chaves or (dados := _json(linha)) is None:
            continue
        if nome := " ".join(str(dados.get("name") or "").split()):
            nomes[partes[1]] = nome
    return nomes


# --- Corte ---


def ramo_do_corte(e: EdicoesDaWork | None, editoras: re.Pattern) -> str | None:
    """`edicoes`, `editora` ou None (fora do corte)."""
    if e is None:
        return None
    if e.quantas >= MIN_EDICOES:
        return "edicoes"
    ano = e.ano_max or 0
    if (
        ano >= ANO_EDITORA
        and (e.quantas >= MIN_EDICOES_EDITORA or ano >= ANO_LANCAMENTO)
        and any(editoras.search(p) for p in e.editoras)
    ):
        return "editora"
    return None


def _conferir_curada(c: Curada, w: WorkLida | None) -> None:
    if w is None:
        raise CuradaInvalida(f"{c.work} ({c.titulo}) não está no dump de works")
    if not normalizar(w.titulo).startswith(normalizar(c.titulo)):
        raise CuradaInvalida(
            f"{c.work}: o título no dump é {w.titulo!r}, não começa por {c.titulo!r}"
        )


# --- Gravação ---


@dataclass(frozen=True)
class ObraTecnica:
    work: str
    titulo: str
    titulo_exibicao: str
    autores: list[str]
    ano: int | None
    descricao: str | None
    capa_url: str | None
    edicoes: int
    curada: bool
    em_portugues: bool
    isbns: list[str]  # os da work e os das duplicadas da lista curada
    assuntos: list[str]


@dataclass(frozen=True)
class ResumoTecnicas:
    works_tecnicas: int
    por_ramo: dict[str, int]
    obras: int  # Obras `open_library` depois da carga
    novas: int
    apagadas: int
    mantidas_em_uso: int  # saíram do corte, mas têm Leitura, lista, Edição ou evento
    do_leitor: int  # Obras do Leitor que viraram técnicas pela work
    com_descricao: int
    com_edicao_pt: int


def _obra_tecnica(
    w: WorkLida, e: EdicoesDaWork | None, nomes: dict[str, str], curada: bool, extras: set[str]
) -> ObraTecnica:
    e = e or EdicoesDaWork()
    return ObraTecnica(
        work=w.chave,
        titulo=w.titulo,
        titulo_exibicao=e.titulo_pt[2] if e.titulo_pt else w.titulo,
        autores=[nomes[a] for a in w.autores if a in nomes],
        ano=w.ano or e.ano_min,
        descricao=w.descricao,
        capa_url=URL_CAPA.format(w.capa) if w.capa else None,
        edicoes=e.quantas,
        curada=curada,
        em_portugues=e.em_portugues,
        isbns=sorted(e.isbns) + sorted(extras - e.isbns),
        assuntos=w.assuntos,
    )


_EM_USO = """
    EXISTS (SELECT 1 FROM leitura x WHERE x.obra_id = o.id)
    OR EXISTS (SELECT 1 FROM dispensa x WHERE x.obra_id = o.id)
    OR EXISTS (SELECT 1 FROM quero_ler x WHERE x.obra_id = o.id)
    OR EXISTS (SELECT 1 FROM estou_lendo x WHERE x.obra_id = o.id)
    OR EXISTS (SELECT 1 FROM edicao x WHERE x.obra_id = o.id)
    OR EXISTS (SELECT 1 FROM evento x WHERE x.obra_id = o.id)
"""


def _gravar(
    conn: Connection, obras: list[ObraTecnica], do_leitor: list[int], genero_id: int
) -> tuple[int, int, int]:
    """Grava as Obras e devolve (novas, apagadas, mantidas em uso)."""
    antes = set(
        conn.execute(text("SELECT ol_work_key FROM obra WHERE origem = 'open_library'")).scalars()
    )
    if obras:
        conn.execute(
            text(
                """
                INSERT INTO obra (titulo, titulo_exibicao, autores, ano_original, descricao,
                                  capa_url, origem, ol_work_key, popularidade, edicoes_ol,
                                  curada, tem_edicao_pt, enriquecida_em)
                VALUES (:titulo, :exibicao, :autores, :ano, :descricao, :capa, 'open_library',
                        :work, 0, :edicoes, :curada, :pt, now())
                ON CONFLICT (ol_work_key) DO UPDATE SET
                    titulo = excluded.titulo, titulo_exibicao = excluded.titulo_exibicao,
                    autores = excluded.autores, ano_original = excluded.ano_original,
                    descricao = excluded.descricao, capa_url = excluded.capa_url,
                    edicoes_ol = excluded.edicoes_ol, curada = excluded.curada,
                    tem_edicao_pt = excluded.tem_edicao_pt, enriquecida_em = now()
                WHERE obra.origem = 'open_library'
                """
            ),
            [
                {
                    "titulo": o.titulo,
                    "exibicao": o.titulo_exibicao,
                    "autores": o.autores,
                    "ano": o.ano,
                    "descricao": o.descricao,
                    "capa": o.capa_url,
                    "work": o.work,
                    "edicoes": o.edicoes,
                    "curada": o.curada,
                    "pt": o.em_portugues,
                }
                for o in obras
            ],
        )
    selecionadas = [o.work for o in obras]
    # Fora do corte: sai se ninguém usa; senão fica, sem os dados da carga anterior mudarem.
    apagadas = conn.execute(
        text(
            f"DELETE FROM obra o WHERE o.origem = 'open_library' "
            f"AND NOT (o.ol_work_key = ANY(:w)) AND NOT ({_EM_USO}) RETURNING o.id"
        ),
        {"w": selecionadas},
    ).all()
    mantidas = conn.execute(
        text(
            "SELECT count(*) FROM obra WHERE origem = 'open_library' "
            "AND NOT (ol_work_key = ANY(:w))"
        ),
        {"w": selecionadas},
    ).scalar_one()
    id_por_work = dict(
        conn.execute(text("SELECT ol_work_key, id FROM obra WHERE origem = 'open_library'")).all()
    )

    # ISBNs, assuntos e Gênero das Obras técnicas da Open Library: refeitos a cada carga.
    conn.execute(
        text(
            "DELETE FROM obra_isbn i USING obra o WHERE o.id = i.obra_id "
            "AND o.origem = 'open_library' AND i.origem = 'open_library'"
        )
    )
    linhas_isbn = {}
    for o in obras:
        for isbn in o.isbns:
            linhas_isbn.setdefault(isbn, id_por_work[o.work])
    if linhas_isbn:
        # Um ISBN que já está em outra Obra (Base, Leitor) fica com ela.
        conn.execute(
            text(
                "INSERT INTO obra_isbn (isbn13, obra_id, origem) "
                "VALUES (:i, :o, 'open_library') ON CONFLICT DO NOTHING"
            ),
            [{"i": i, "o": o} for i, o in linhas_isbn.items()],
        )
    conn.execute(
        text(
            "DELETE FROM obra_tag t USING obra o "
            "WHERE o.id = t.obra_id AND o.origem = 'open_library'"
        )
    )
    linhas_tag = [
        {"o": id_por_work[o.work], "t": a} for o in obras for a in dict.fromkeys(o.assuntos)
    ]
    if linhas_tag:
        conn.execute(
            text("INSERT INTO obra_tag (obra_id, tag, contagem) VALUES (:o, :t, 0)"), linhas_tag
        )
    conn.execute(
        text(
            "DELETE FROM obra_genero g USING obra o "
            "WHERE o.id = g.obra_id AND o.origem = 'open_library'"
        )
    )
    tecnicas = sorted({*id_por_work.values(), *do_leitor})
    if tecnicas:
        conn.execute(
            text(
                "INSERT INTO obra_genero (obra_id, genero_id, forca) "
                "SELECT o, :g, 1 FROM unnest(CAST(:obras AS bigint[])) AS o "
                "ON CONFLICT (obra_id, genero_id) DO UPDATE SET forca = 1"
            ),
            {"g": genero_id, "obras": tecnicas},
        )
    # Uma Edição em português gravada pelo Leitor continua valendo (§7.2).
    conn.execute(
        text(
            "UPDATE obra o SET tem_edicao_pt = true WHERE o.origem = 'open_library' "
            "AND EXISTS (SELECT 1 FROM edicao e WHERE e.obra_id = o.id AND e.idioma = 'pt')"
        )
    )
    return len(set(selecionadas) - antes), len(apagadas), mantidas


def carregar_tecnicas(
    conn: Connection,
    pasta_dumps: Path,
    *,
    assuntos: Path = ARQUIVO_ASSUNTOS,
    editoras: Path = ARQUIVO_EDITORAS,
    curados: Path = ARQUIVO_CURADOS,
) -> ResumoTecnicas:
    criterio = ler_criterio(assuntos)
    re_editoras = ler_editoras(editoras)
    curadas = ler_curados(curados)
    genero_id = conn.execute(
        text("SELECT id FROM genero WHERE slug = :s"), {"s": SLUG_TECNOLOGIA}
    ).scalar_one_or_none()
    if genero_id is None:
        raise RuntimeError("Gênero Tecnologia ausente: rode `mapear-generos` antes")
    works_dump = localizar_dump(pasta_dumps, "works")
    editions_dump = localizar_dump(pasta_dumps, "editions")
    authors_dump = localizar_dump(pasta_dumps, "authors")

    principais = {c.work for c in curadas}
    duplicadas = {f for c in curadas for f in c.fundir}
    log.info("Passada 1/3 (%s): works técnicas e da lista curada", works_dump.name)
    tecnicas, da_lista = _ler_works(works_dump, criterio, principais | duplicadas)
    for c in curadas:
        _conferir_curada(c, da_lista.get(c.work))
    log.info("  %d works técnicas fora do ruído; %d da lista curada", len(tecnicas), len(curadas))

    log.info("Passada 2/3 (%s): Edições", editions_dump.name)
    edicoes = _ler_edicoes(editions_dump, set(tecnicas) | principais | duplicadas)

    # Uma work que já é de uma Obra da Base ou do Leitor não vira Obra nova (§8.8, passo 6).
    ocupadas = {
        r.ol_work_key: (r.id, r.origem)
        for r in conn.execute(
            text(
                "SELECT ol_work_key, id, origem::text AS origem FROM obra "
                "WHERE origem IN ('base', 'leitor') AND ol_work_key IS NOT NULL"
            )
        )
    }
    escolhidas: dict[str, tuple[WorkLida, bool, set[str]]] = {}
    por_ramo = {"edicoes": 0, "editora": 0, "curada": 0}
    do_leitor: list[int] = []
    da_base = 0

    def ocupada(chave: str) -> bool:
        nonlocal da_base
        if chave not in ocupadas:
            return False
        obra_id, origem = ocupadas[chave]
        if origem == "leitor":
            do_leitor.append(obra_id)
        else:
            da_base += 1
        return True

    for chave, w in tecnicas.items():
        if chave in duplicadas or chave in principais:
            continue
        if (ramo := ramo_do_corte(edicoes.get(chave), re_editoras)) and not ocupada(chave):
            por_ramo[ramo] += 1
            escolhidas[chave] = (w, False, set())
    for c in curadas:
        if not ocupada(c.work):
            extras = {i for f in c.fundir for i in edicoes.get(f, EdicoesDaWork()).isbns}
            escolhidas[c.work] = (da_lista[c.work], True, extras)
            por_ramo["curada"] += 1
    if da_base:
        log.info("  %d works já são de Obras da Base e ficam como estão", da_base)

    log.info("Passada 3/3 (%s): autores", authors_dump.name)
    nomes = _ler_autores(authors_dump, {a for w, _, _ in escolhidas.values() for a in w.autores})
    obras = [
        _obra_tecnica(w, edicoes.get(k), nomes, curada, extras)
        for k, (w, curada, extras) in escolhidas.items()
    ]
    novas, apagadas, mantidas = _gravar(conn, obras, do_leitor, genero_id)
    resumo = ResumoTecnicas(
        works_tecnicas=len(tecnicas),
        por_ramo=por_ramo,
        obras=conn.execute(
            text("SELECT count(*) FROM obra WHERE origem = 'open_library'")
        ).scalar_one(),
        novas=novas,
        apagadas=apagadas,
        mantidas_em_uso=mantidas,
        do_leitor=len(do_leitor),
        com_descricao=sum(o.descricao is not None for o in obras),
        com_edicao_pt=sum(o.em_portugues for o in obras),
    )
    _registrar(resumo)
    return resumo


def _registrar(r: ResumoTecnicas) -> None:
    log.info("Obras técnicas da Open Library: %d (%d novas)", r.obras, r.novas)
    log.info(
        "  por ramo do corte: ≥ %d Edições %d; editora técnica %d; lista curada %d",
        MIN_EDICOES,
        r.por_ramo["edicoes"],
        r.por_ramo["editora"],
        r.por_ramo["curada"],
    )
    log.info("  com descrição: %d; com Edição em português: %d", r.com_descricao, r.com_edicao_pt)
    log.info(
        "  apagadas (fora do corte e sem uso): %d; fora do corte e em uso: %d",
        r.apagadas,
        r.mantidas_em_uso,
    )
    log.info("  Obras do Leitor que viraram técnicas pela work: %d", r.do_leitor)
