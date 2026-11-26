"""Quais tags de leitores descrevem a Obra, e não a relação do leitor com ela (SPEC §6.1)."""

import re
from functools import lru_cache
from pathlib import Path

_ARQUIVO_IGNORADAS = Path(__file__).with_name("tags_ignoradas.txt")

# Padrões que a lista exata não cobre. Um "token" é um trecho entre hífens: `(^|-)x(-|$)`.
_PADROES_IGNORADOS = [
    # Anos ("read-in-2015", "2016-reads"; "20th-century" fica), notas ("5-stars") e tags sem
    # nenhuma letra ("-", "--1-").
    re.compile(r"(^|\D)(19|20)\d\d(\D|$)"),
    re.compile(r"^\d+(\.\d+)?-stars?$"),
    re.compile(r"^[^a-z]*$"),
    # Status de leitura: "to-read-fiction", "classics-to-read", "tbr-pile", "own-unread",
    # "reread", "already-read", "books-i-ve-read". As listas que começam por número ficam
    # ("1001-books-to-read", "1001-books-to-read-before-you-die").
    re.compile(r"^to-(be-)?read(-|$)"),
    re.compile(r"^[a-z].*-to-(be-)?read$"),
    re.compile(r"(^|-)(tbr|unread|re-?read(s|ing)?)(-|$)"),
    re.compile(
        r"(^|-)(already|have|half|partially|partly|recently|never|not|done|maybe|might)-read$"
    ),
    re.compile(r"(^|-)i-(ve|have|already-have)-read$"),
    re.compile(r"^(finished|done)(-|$)"),
    re.compile(r"(^|-)(currently|stopped|done|finish|finished|always)-reading$"),
    re.compile(
        r"(^|-)(dnf|gave-up)(-|$)|^(did|didn-t|could|couldn-t|never|not)(-not)?-finish(ed)?$"
    ),
    # Gênero + status: "comics-read", "manga-read", "stephen-king-read", "read-manga",
    # "read-in-english". Ficam as que dizem que tipo de leitura a Obra é ("beach-read",
    # "must-read", "read-aloud") e as de escola e infância ("read-for-school", "read-as-a-kid").
    re.compile(
        r"^(?!.*(^|-)(must|beach|quick|dark|easy|fast|light|fun|good|great|big|riot|christmas|can"
        r"|holiday|summer|comfort|gentle)-read$)[a-z].*-read$"
    ),
    re.compile(r"^read-(?!alouds?$|to-|for-school|in-school|in-\d|in-[a-z]+-grade|as-a-)"),
    # Posse: "owned", "own-kindle", "books-i-own", "want-to-own", "books-i-have".
    # "own-voices" (autor do grupo retratado) descreve a Obra.
    re.compile(r"^(?!own-voices$).*(^|-)own(ed)?(-|$)"),
    re.compile(r"(^|-)i-have(-it)?$|^(a|1)-have$|^have-(it|but|to)(-|$)"),
    # Estante pessoal: "my-favorites", "on-my-shelf", "in-my-library", "bookshelf".
    # Ficam títulos e séries ("my-blood-approves", "out-of-my-mind").
    re.compile(r"^(on-|in-|books-(in|on|from)-|from-)?my-(?!blood-approves)"),
    re.compile(r"(^|-)(book-?)?shel(f|ves)$(?<!our-shared-shelf)|^shelfari(-|$)"),
    # Biblioteca: "library-book", "home-library", "borrowed-from-library". Ficam as coleções
    # de editora ("modern-library-100", "library-of-america", "everyman-s-library").
    re.compile(
        r"^(?!.*(modern-library|library-of-america|penguin-english-library|everyman-s-library"
        r"|black-library)).*(^|-)librar(y|ies)(-|$)"
    ),
    # Formato: "kindle-books", "nook", "my-ebooks", "pdf", "audible", "paperback".
    re.compile(
        r"(^|-)(kindle|nook|kobo|ebooks?|e-books?|epubs?|pdf|calibre|audible|audio|audiobooks?"
        r"|audio-books?|overdrive|ku|kindle-unlimited|paperbacks?|hardcovers?|hardbacks?"
        r"|hard-copy|ereader|e-reader|ibooks)(-|$)"
    ),
    # Aquisição: "need-to-buy", "wish-list", "netgalley", "arc", "first-reads", "freebie".
    re.compile(r"(^|-)to-(buy|purchase|get|find)(-|$)|^buy(-|$)"),
    re.compile(
        r"(^|-)(bought|purchased|borrowed|borrow|gifted|donated|freebies?|giveaways?|arcs?"
        r"|netgalley|first-reads|wish-?list)(-|$)"
    ),
    # Preferência: "favorite-authors", "childhood-favorites", "faves", "all-time-favs".
    re.compile(r"(^|-)(favou?rites?|favou?rits?|favs?|faves?|favoritos)(-|$)"),
    # Clube de leitura genérico: "book-club-books", "book-group". Os clubes com nome
    # ficam, porque são listas de fora ("oprah-s-book-club", "our-shared-shelf-book-club").
    re.compile(r"^book-?(clubs?|groups?)(-|read|$)"),
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
