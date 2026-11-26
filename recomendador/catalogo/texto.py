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
# Títulos no início do nome ("Dr. Yuxing Yan", "Prof. Diwakar Vaish"), que não são o primeiro nome.
_TITULOS = frozenset("dr dra prof profa".split())
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


def _sem_titulo(partes: list[str]) -> list[str]:
    """As partes do nome sem o título do início ("Dr.", "Prof."), se sobrarem duas ou mais.

    Com uma só, o título é do nome: o Dr. Seuss não vira "Seuss".
    """
    if len(partes) > 2 and partes[0] in _TITULOS:
        return partes[1:]
    return partes


def chave_do_autor(nome: str) -> tuple[str, str | None] | None:
    """(primeiro nome, sobrenome): "Kevin E. Kline" e "Kevin Kline" dão a mesma chave.

    O título do início não conta: "Dr. Yuxing Yan" e "Yuxing Yan" também.
    """
    partes = _sem_titulo(normalizar(nome).split())
    return (partes[0], sobrenome(nome)) if partes else None


def sem_autores_repetidos(nomes: list[str]) -> list[str]:
    """Um nome por autor, na ordem da primeira vez que aparece.

    Dois nomes são o mesmo autor se têm o mesmo primeiro nome e o mesmo sobrenome
    ("Kevin E. Kline" e "Kevin Kline"); fica a forma mais completa. O título do início não
    conta no tamanho: entre "Yuxing Yan" e "Dr. Yuxing Yan", fica o que veio primeiro.
    """

    def tamanho(nome: str) -> int:
        return len(" ".join(_sem_titulo(normalizar(nome).split())))

    por_chave: dict[tuple[str, str | None], str] = {}
    for nome in nomes:
        if (chave := chave_do_autor(nome)) is None:
            continue
        atual = por_chave.get(chave)
        if atual is None or tamanho(nome) > tamanho(atual):
            por_chave[chave] = nome
    return list(por_chave.values())


# O que as livrarias põem no fim do título e não é dele: o idioma ("(Em Portugues do
# Brasil)", "(Portuguese Edition)"), prêmios ("(Prémio LeYa 2018)", "(Pulitzer Prize
# Winner)") e selos da Edição ("(Edição de bolso)", "(Tradução Atualizada)", "-(EURO 17.46)").
# Série e coleção ficam: "(House of Night #6)", "(Coleção Duetos)".
_RUIDO = r"""
    portugu | brasil
    | \b(?: pr[eéê]mios?\b | premiad[oa]\b | vencedor | finalista | award | prize | winner )
    | \bedi[cç][aã]o\s+(?: especial | comemorativa | de\s+bolso | de\s+luxo | ilustrada
                         | definitiva | de\s+colecionador )\b
    | \bilustrad[oa]s?\b
    | \btradu[cç][aã]o\s+(?: atualizada | revista | de\s+\d{4} )\b
    | \bleitura\s+f[aá]cil\b
    | \beuro\s*\d
"""
_RE_RUIDO_DO_TITULO = re.compile(
    rf"\s*-?\s*\([^()]*(?:{_RUIDO})[^()]*\)\s*$", re.IGNORECASE | re.VERBOSE
)


def titulo_sem_ruido(titulo: str) -> str:
    """O título sem os parênteses finais de idioma, prêmio ou selo da Edição."""
    while (limpo := _RE_RUIDO_DO_TITULO.sub("", titulo)) != titulo and limpo:
        titulo = limpo
    return " ".join(titulo.split())
