import pytest

from recomendador.catalogo.isbn import normalizar_isbn, parece_isbn
from recomendador.catalogo.tags import tag_util


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("0439023483", "9780439023481"),
        ("043965548X", "9780439655484"),
        ("043965548x", "9780439655484"),
        ("978-0-439-02348-1", "9780439023481"),
        ("9780439023481", "9780439023481"),
        ("9780439023482", None),  # dígito verificador errado
        ("0439023484", None),
        ("12345", None),
        ("", None),
        (None, None),
    ],
)
def test_normalizar_isbn(entrada: str | None, esperado: str | None) -> None:
    assert normalizar_isbn(entrada) == esperado


def test_parece_isbn() -> None:
    assert parece_isbn("978-85-7657-313-0")
    assert parece_isbn("043965548X")
    assert not parece_isbn("Duna")
    assert not parece_isbn("1984")


@pytest.mark.parametrize(
    "tag",
    [
        "fantasy",
        "science-fiction",
        "20th-century",
        "1001-books",
        # Parecem status ou posse, mas descrevem a Obra (SPEC §6.1).
        "mystery",
        "mythology",
        "my-blood-approves",
        "own-voices",
        "1001-books-to-read-before-you-die",
        "1001-books-to-read",
        "books-to-read-in-your-20s",
        "must-read",
        "beach-read",
        "beach-reads",
        "read-aloud",
        "read-for-school",
        "read-as-a-kid",
        "i-can-read",
        "modern-library-100",
        "library-of-america",
        "oprah-s-book-club",
        "our-shared-shelf",
        "kingdom-keepers",
        "completed-series",
        "first-in-series",
    ],
)
def test_tags_que_descrevem_a_obra(tag: str) -> None:
    assert tag_util(tag)


@pytest.mark.parametrize(
    "tag",
    [
        "to-read",
        "favorites",
        "kindle",
        "read-in-2015",
        "2016-reads",
        "5-stars",
        "--1-",
        "-",
        # Status de leitura
        "tbr",
        "tbr-pile",
        "to-read-fiction",
        "classics-to-read",
        "want-to-read",
        "own-to-read",
        "reread",
        "to-re-read",
        "already-read",
        "books-i-ve-read",
        "finished",
        "didn-t-finish",
        "couldn-t-finish",
        "gave-up-on",
        "unfinished",
        "comics-read",
        "read-manga",
        "read-in-english",
        # Posse e formato
        "own-kindle",
        "books-i-have",
        "my-bookshelf",
        "on-my-shelf",
        "my-ebooks",
        "nook",
        "kindle-books",
        "kindle-unlimited",
        "library-book",
        "library-books",
        "home-library",
        "paperback",
        "calibre",
        "need-to-buy",
        "netgalley",
        "arc",
        "first-reads",
        # Preferência e organização
        "my-favorites",
        "favorite-authors",
        "favorite-series",
        "childhood-favorites",
        "faves",
        "book-club-books",
        "book-club-reads",
        "book-group",
        "recommended",
    ],
)
def test_tags_ignoradas(tag: str) -> None:
    assert not tag_util(tag)
