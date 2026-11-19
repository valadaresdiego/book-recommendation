"""Normalização de texto para comparar títulos e nomes (busca e regra 3 do SPEC §7.2)."""

import re
import unicodedata

_NAO_ALFANUMERICO = re.compile(r"[^0-9a-z]+")
# Palavras que não ajudam a achar uma Obra e só diluem a semelhança.
PALAVRAS_VAZIAS = frozenset(
    "a as o os e de da das do dos em no na nos nas um uma the of and an".split()
)
# Sufixos que não são sobrenome ("Itamar Vieira Junior", "Martin Luther King Jr.").
_SUFIXOS = frozenset("jr junior filho neto sobrinho sr ii iii iv".split())
# O filtro de editora da busca (SPEC §7.1), com aspas retas ou curvas para mais de uma palavra.
_RE_EDITORA = re.compile(r'\beditora:\s*(?:"([^"]*)"|“([^”]*)”|(\S+))', re.IGNORECASE)


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação, com espaços simples."""
    if texto.isascii():  # caminho rápido, para os milhões de títulos do dump de works
        return _NAO_ALFANUMERICO.sub(" ", texto.lower()).strip()
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _NAO_ALFANUMERICO.sub(" ", sem_acento.lower()).strip()


def palavras_da_busca(texto: str) -> list[str]:
    """As palavras que contam na busca, sem repetição e sem as vazias (se sobrar alguma)."""
    todas = list(dict.fromkeys(normalizar(texto).split()))
    uteis = [p for p in todas if p not in PALAVRAS_VAZIAS]
    return uteis or todas


def separar_editora(texto: str) -> tuple[str, str | None]:
    """Tira da busca o filtro `editora:` e devolve (o resto do texto, a editora).

    Sem aspas, a editora é uma palavra (`editora:packt django`); com aspas, pode ter mais
    (`editora:"alta books" python`). Sem o filtro, devolve o texto como veio e `None`.
    """
    achado = _RE_EDITORA.search(texto)
    if achado is None:
        return texto, None
    editora = next(g for g in achado.groups() if g is not None).strip()
    resto = " ".join((texto[: achado.start()] + " " + texto[achado.end() :]).split())
    return resto, editora or None


def sobrenome(nome: str) -> str | None:
    """O último sobrenome, sem sufixos como Jr., Filho ou Neto."""
    partes = [p for p in normalizar(nome).split() if p not in _SUFIXOS]
    return partes[-1] if partes else None
