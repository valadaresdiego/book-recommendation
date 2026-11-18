"""Tipos que o Catálogo devolve ao `app/` (SPEC §7.1 e §7.2)."""

from dataclasses import dataclass, field
from typing import Literal

Confianca = Literal["catalogo", "isbn", "ol_work", "titulo_original", "nova"]


@dataclass(frozen=True)
class ResultadoBusca:
    """Um item da busca do R1: uma Obra do Catálogo, uma Edição do Google Books, ou as duas.

    - `obra_id` preenchido: está no Catálogo ("no catálogo"), sem precisar de resolução.
    - `google_volume_id` preenchido: veio do Google Books; os demais campos são da Edição.
    - Os dois: uma Edição do Google Books cujo ISBN já está em `obra_isbn` (item fundido).
    """

    titulo: str
    autores: tuple[str, ...]
    ano: int | None
    capa_url: str | None
    obra_id: int | None = None
    google_volume_id: str | None = None
    isbns: tuple[str, ...] = ()  # ISBN-13 da Edição
    editora: str | None = None
    idioma: str | None = None  # ISO 639-1 (pt, en...)
    descricao: str | None = None
    titulo_obra: str | None = None  # `titulo_exibicao` da Obra, quando difere do da Edição

    @property
    def no_catalogo(self) -> bool:
        return self.obra_id is not None


@dataclass(frozen=True)
class Candidata:
    """Uma Obra do Catálogo próxima da Edição escolhida, para a pergunta "É uma destas?"."""

    obra_id: int
    titulo: str
    autores: tuple[str, ...]
    ano: int | None
    capa_url: str | None


@dataclass(frozen=True)
class ObraProposta:
    """Os dados de uma Obra `origem='leitor'` ainda não gravada (regra 4 do SPEC §7.2)."""

    titulo: str
    titulo_original: str | None
    titulo_exibicao: str
    autores: tuple[str, ...]
    ano_original: int | None
    descricao: str | None
    capa_url: str | None
    ol_work_key: str | None
    assuntos: tuple[str, ...] = ()
    isbns: tuple[str, ...] = ()
    enriquecida: bool = False  # True se os dados vieram da Open Library


@dataclass(frozen=True)
class Resolucao:
    """O resultado de `resolver_obra`: a Obra encontrada, ou uma Obra nova e as candidatas.

    Resolver não grava nada. `registrar_resolucao` grava a Edição e, se for o caso,
    a Obra nova, quando o Leitor confirma.
    """

    confianca: Confianca
    edicao: ResultadoBusca | None  # a Edição escolhida (None no cadastro manual)
    obra_id: int | None = None  # Obra do Catálogo encontrada pelas regras 1 a 3
    obra_nova: ObraProposta | None = None  # regra 4
    candidatas: tuple[Candidata, ...] = field(default=())
    edicao_ol: str | None = None  # chave da Edição na Open Library (/books/OL…M), se achada

    @property
    def encontrou(self) -> bool:
        return self.obra_id is not None
