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


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação, com espaços simples."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _NAO_ALFANUMERICO.sub(" ", sem_acento.lower()).strip()


def palavras_da_busca(texto: str) -> list[str]:
    """As palavras que contam na busca, sem repetição e sem as vazias (se sobrar alguma)."""
    todas = list(dict.fromkeys(normalizar(texto).split()))
    uteis = [p for p in todas if p not in PALAVRAS_VAZIAS]
    return uteis or todas


def sobrenome(nome: str) -> str | None:
    """O último sobrenome, sem sufixos como Jr., Filho ou Neto."""
    partes = [p for p in normalizar(nome).split() if p not in _SUFIXOS]
    return partes[-1] if partes else None
