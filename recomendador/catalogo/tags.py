"""Quais tags de leitores descrevem a Obra, e não a relação do leitor com ela (SPEC §6.1)."""

import re
from functools import lru_cache
from pathlib import Path

_ARQUIVO_IGNORADAS = Path(__file__).with_name("tags_ignoradas.txt")

# Padrões que a lista exata não cobre: anos ("read-in-2015", "2016-reads", "20th-century" fica),
# notas ("5-stars") e tags sem nenhuma letra ("-", "--1-").
_PADROES_IGNORADOS = [
    re.compile(r"(^|\D)(19|20)\d\d(\D|$)"),
    re.compile(r"^\d+(\.\d+)?-stars?$"),
    re.compile(r"^[^a-z]*$"),
]


@lru_cache
def tags_ignoradas() -> frozenset[str]:
    linhas = _ARQUIVO_IGNORADAS.read_text(encoding="utf-8").splitlines()
    return frozenset(s for linha in linhas if (s := linha.strip()) and not s.startswith("#"))


def tag_util(tag: str) -> bool:
    tag = tag.strip().lower()
    if tag in tags_ignoradas():
        return False
    return not any(p.search(tag) for p in _PADROES_IGNORADOS)
