"""Importação do histórico do Goodreads (R9, SPEC §8.9, ADR 0011).

Três passos, para a UI mostrar o que vai acontecer antes de gravar:

1. `ler_goodreads` lê o CSV exportado e devolve as linhas, sem tocar no banco.
2. `preparar_importacao` passa cada linha pela Resolução (`catalogo.resolver_obra`, SPEC
   §7.2) e separa as que acharam a Obra das que caíram na regra 4. Não grava nada.
3. `importar` grava as encontradas; `importar_linha` grava uma linha da revisão, depois que
   o Leitor respondeu "É uma destas?".

Vale a Estante: uma Obra que já está lá não muda. A revisão não é guardada, e reimportar o
mesmo arquivo pula o que já entrou.
"""

import csv
import io
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, get_args

from sqlalchemy import Connection

from recomendador.catalogo.fontes.open_library import OpenLibrary
from recomendador.catalogo.isbn import normalizar_isbn
from recomendador.catalogo.resolucao import registrar_isbns, registrar_resolucao, resolver_obra
from recomendador.catalogo.tipos import Resolucao, ResultadoBusca
from recomendador.estante.eventos import registrar_evento
from recomendador.estante.leituras import adicionar, leitura_da_obra
from recomendador.estante.listas import (
    na_lista_estou_lendo,
    na_lista_quero_ler,
    salvar_estou_lendo,
    salvar_quero_ler,
)

EstadoImportado = Literal["lida", "lendo", "quero_ler"]
Destino = Literal["estante", "quero_ler", "estou_lendo", "ja_na_estante", "ja_na_lista"]

COLUNAS_DO_GOODREADS = ("Title", "Author", "ISBN", "ISBN13", "My Rating", "Exclusive Shelf")
_ESTADOS: dict[str, EstadoImportado] = {
    "read": "lida",
    "currently-reading": "lendo",
    "to-read": "quero_ler",
}
_PRIORIDADE = {"quero_ler": 0, "lendo": 1, "lida": 2}
# O mesmo sufixo de série que a carga do goodbooks tira (SPEC §6.1): "(The First Law, #1)".
_SUFIXO_DE_SERIE = re.compile(r"\s*\([^()]*#[^()]*\)\s*$")
_FORMATOS_DE_DATA = ("%Y/%m/%d", "%Y-%m-%d")


class ArquivoInvalido(ValueError):
    """O arquivo não é um CSV exportado do Goodreads."""


@dataclass(frozen=True)
class LinhaImportada:
    """Uma linha do arquivo, já limpa: título sem a série, ISBN-13, Nota de 1 a 5 ou nula."""

    numero: int  # a linha no arquivo, contando o cabeçalho (a primeira é a 2)
    titulo: str
    autores: tuple[str, ...]
    isbns: tuple[str, ...]
    nota: int | None
    estado: EstadoImportado | None  # None: prateleira que não entra (did-not-finish...)
    prateleira: str  # `Exclusive Shelf`, como veio
    data: date | None  # `Date Read` ou, sem ela, `Date Added`; só ordena a gravação


@dataclass(frozen=True)
class LinhaResolvida:
    linha: LinhaImportada
    resolucao: Resolucao

    @property
    def obra_id(self) -> int | None:
        return self.resolucao.obra_id


@dataclass(frozen=True)
class Previa:
    """O que a importação faria. `encontradas` tem Obra; `sem_correspondencia` vai para a
    revisão, com a Obra proposta e as candidatas da regra 4."""

    fonte: str
    linhas: int
    encontradas: tuple[LinhaResolvida, ...]
    sem_correspondencia: tuple[LinhaResolvida, ...]
    ignoradas: tuple[LinhaImportada, ...]
    ja_na_estante: int  # encontradas cuja Obra já é uma Leitura

    @property
    def taxa(self) -> float:
        """A fração das linhas resolvidas que achou a Obra no Catálogo."""
        resolvidas = len(self.encontradas) + len(self.sem_correspondencia)
        return len(self.encontradas) / resolvidas if resolvidas else 0.0


@dataclass(frozen=True)
class ObraJaNaEstante:
    obra_id: int
    titulo: str  # `titulo_exibicao`
    nota_estante: int | None
    nota_arquivo: int | None


@dataclass(frozen=True)
class Desfecho:
    """O que aconteceu com uma linha gravada."""

    obra_id: int
    destino: Destino
    ja_na_estante: ObraJaNaEstante | None = None


@dataclass(frozen=True)
class Relatorio:
    leituras: int
    quero_ler: int
    estou_lendo: int
    ja_na_estante: tuple[ObraJaNaEstante, ...]
    ja_na_lista: int
    repetidas: int  # linhas que caíram numa Obra já trazida por outra linha do arquivo
    sem_correspondencia: int
    ignoradas: int


# --- Leitura do arquivo ---


def _isbn(valor: str | None) -> str | None:
    # O Goodreads exporta o ISBN como fórmula de planilha: ="9780439023481", vazio ="".
    return normalizar_isbn((valor or "").strip().lstrip("=").strip('"'))


def _nota(valor: str | None) -> int | None:
    try:
        nota = int(float(valor or 0))  # uma meia nota iria para baixo (ADR 0011)
    except ValueError:
        return None
    return nota if 1 <= nota <= 5 else None


def _data(valor: str | None) -> date | None:
    for formato in _FORMATOS_DE_DATA:
        try:
            return datetime.strptime((valor or "").strip(), formato).date()
        except ValueError:
            continue
    return None


def _autores(principal: str | None, adicionais: str | None) -> tuple[str, ...]:
    nomes = [principal or "", *(adicionais or "").split(",")]
    return tuple(dict.fromkeys(n for n in (" ".join(x.split()) for x in nomes) if n))


def _titulo(titulo: str) -> str:
    titulo = " ".join(titulo.split())
    return _SUFIXO_DE_SERIE.sub("", titulo).strip() or titulo


def ler_goodreads(conteudo: bytes) -> list[LinhaImportada]:
    """Lê o CSV do "Export Library" do Goodreads. As colunas valem pelo nome."""
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ArquivoInvalido("O arquivo não está em UTF-8: não parece um CSV do Goodreads.") from e
    leitor = csv.DictReader(io.StringIO(texto, newline=""))
    faltam = [c for c in COLUNAS_DO_GOODREADS if c not in (leitor.fieldnames or ())]
    if faltam:
        raise ArquivoInvalido(
            f"Não parece um export do Goodreads: faltam as colunas {', '.join(faltam)}."
        )
    linhas = []
    for numero, registro in enumerate(leitor, start=2):
        titulo = _titulo(registro.get("Title") or "")
        if not titulo:
            continue
        prateleira = (registro.get("Exclusive Shelf") or "").strip()
        isbns = (_isbn(registro.get("ISBN13")), _isbn(registro.get("ISBN")))
        linhas.append(
            LinhaImportada(
                numero=numero,
                titulo=titulo,
                autores=_autores(registro.get("Author"), registro.get("Additional Authors")),
                isbns=tuple(dict.fromkeys(i for i in isbns if i)),
                nota=_nota(registro.get("My Rating")),
                estado=_ESTADOS.get(prateleira.lower()),
                prateleira=prateleira,
                data=_data(registro.get("Date Read")) or _data(registro.get("Date Added")),
            )
        )
    return linhas


# --- Prévia ---


def _como_edicao(linha: LinhaImportada) -> ResultadoBusca:
    """A linha como a Resolução a recebe: título, autores e ISBNs, sem volume do Google Books.

    Sem volume, `registrar_resolucao` não grava Edição; os ISBNs vão para a Obra no
    `importar` (`registrar_isbns`).
    """
    return ResultadoBusca(
        titulo=linha.titulo, autores=linha.autores, ano=None, capa_url=None, isbns=linha.isbns
    )


def preparar_importacao(
    conn: Connection,
    leitor_id: uuid.UUID,
    linhas: Iterable[LinhaImportada],
    ol: OpenLibrary | None,
    ao_avancar: Callable[[int, int], None] | None = None,
) -> Previa:
    """Resolve cada linha pela ordem do SPEC §7.2. Não grava nada.

    As linhas de prateleiras que não entram nem passam pela Resolução. `ao_avancar(feitas,
    total)` é chamada depois de cada linha, para a barra de progresso: uma linha cujo ISBN
    não está no Catálogo consulta a Open Library, a 1 req/s.
    """
    linhas = list(linhas)
    a_resolver = [linha for linha in linhas if linha.estado is not None]
    encontradas: list[LinhaResolvida] = []
    sem_correspondencia: list[LinhaResolvida] = []
    for feitas, linha in enumerate(a_resolver, start=1):
        resolvida = LinhaResolvida(linha, resolver_obra(conn, _como_edicao(linha), ol))
        (encontradas if resolvida.resolucao.encontrou else sem_correspondencia).append(resolvida)
        if ao_avancar is not None:
            ao_avancar(feitas, len(a_resolver))
    ja_na_estante = sum(
        1
        for obra_id in {r.obra_id for r in encontradas}
        if leitura_da_obra(conn, leitor_id, obra_id) is not None
    )
    return Previa(
        fonte="goodreads",
        linhas=len(linhas),
        encontradas=tuple(encontradas),
        sem_correspondencia=tuple(sem_correspondencia),
        ignoradas=tuple(linha for linha in linhas if linha.estado is None),
        ja_na_estante=ja_na_estante,
    )


# --- Gravação ---


def _gravar(
    conn: Connection, leitor_id: uuid.UUID, linha: LinhaImportada, obra_id: int
) -> Desfecho:
    """Põe a Obra onde a linha diz, se ela ainda não está lá nem na Estante."""
    if existente := leitura_da_obra(conn, leitor_id, obra_id):
        ja = ObraJaNaEstante(obra_id, existente.titulo, existente.nota, linha.nota)
        return Desfecho(obra_id, "ja_na_estante", ja)
    if linha.estado == "lida":
        adicionar(conn, leitor_id, obra_id, linha.nota, origem="importacao")
        destino: Destino = "estante"
    elif linha.estado == "lendo":
        if na_lista_estou_lendo(conn, leitor_id, obra_id):
            return Desfecho(obra_id, "ja_na_lista")
        salvar_estou_lendo(conn, leitor_id, obra_id)
        destino = "estou_lendo"
    else:
        # Quem já começou a ler não volta para Quero ler.
        if na_lista_quero_ler(conn, leitor_id, obra_id) or na_lista_estou_lendo(
            conn, leitor_id, obra_id
        ):
            return Desfecho(obra_id, "ja_na_lista")
        salvar_quero_ler(conn, leitor_id, obra_id)
        destino = "quero_ler"
    registrar_isbns(conn, obra_id, linha.isbns)
    return Desfecho(obra_id, destino)


def _preferida(r: LinhaResolvida) -> tuple:
    """Entre as linhas da mesma Obra: lida, depois lendo, depois quero ler; com Nota; a mais
    recente."""
    linha = r.linha
    return (_PRIORIDADE[linha.estado], linha.nota is not None, linha.data or date.min, linha.numero)


def _ordem_de_gravacao(r: LinhaResolvida) -> tuple:
    """Da mais antiga para a mais nova: a Estante desempata a data de inclusão pelo id."""
    return (r.linha.data is None, r.linha.data or date.min, r.linha.numero)


def importar(conn: Connection, leitor_id: uuid.UUID, previa: Previa) -> Relatorio:
    """Grava as linhas encontradas e registra `historico_importado`. Vale a Estante."""
    por_obra: dict[int, LinhaResolvida] = {}
    for r in previa.encontradas:
        if r.obra_id not in por_obra or _preferida(r) > _preferida(por_obra[r.obra_id]):
            por_obra[r.obra_id] = r
    desfechos = [
        _gravar(conn, leitor_id, r.linha, r.obra_id)
        for r in sorted(por_obra.values(), key=_ordem_de_gravacao)
    ]
    contagem = {d: sum(1 for x in desfechos if x.destino == d) for d in get_args(Destino)}
    relatorio = Relatorio(
        leituras=contagem["estante"],
        quero_ler=contagem["quero_ler"],
        estou_lendo=contagem["estou_lendo"],
        ja_na_estante=tuple(d.ja_na_estante for d in desfechos if d.ja_na_estante),
        ja_na_lista=contagem["ja_na_lista"],
        repetidas=len(previa.encontradas) - len(por_obra),
        sem_correspondencia=len(previa.sem_correspondencia),
        ignoradas=len(previa.ignoradas),
    )
    registrar_evento(
        conn,
        leitor_id,
        "historico_importado",
        fonte=previa.fonte,
        linhas=previa.linhas,
        leituras=relatorio.leituras,
        quero_ler=relatorio.quero_ler,
        estou_lendo=relatorio.estou_lendo,
        ja_na_estante=len(relatorio.ja_na_estante),
        repetidas=relatorio.repetidas,
        sem_correspondencia=relatorio.sem_correspondencia,
        ignoradas=relatorio.ignoradas,
    )
    return relatorio


def importar_linha(
    conn: Connection, leitor_id: uuid.UUID, resolvida: LinhaResolvida, escolha: int | None = None
) -> Desfecho:
    """Uma linha da revisão: `escolha` é a candidata de "É uma destas?"; sem ela, cria a Obra
    proposta (ou usa a que o título original achou, `catalogo.informar_titulo_original`)."""
    registrada = registrar_resolucao(conn, resolvida.resolucao, escolha=escolha)
    return _gravar(conn, leitor_id, resolvida.linha, registrada.obra_id)
