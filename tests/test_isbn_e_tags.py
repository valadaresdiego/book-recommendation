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


@pytest.mark.parametrize("tag", ["fantasy", "science-fiction", "20th-century", "1001-books"])
def test_tags_que_descrevem_a_obra(tag: str) -> None:
    assert tag_util(tag)


@pytest.mark.parametrize(
    "tag", ["to-read", "favorites", "kindle", "read-in-2015", "2016-reads", "5-stars", "--1-", "-"]
)
def test_tags_ignoradas(tag: str) -> None:
    assert not tag_util(tag)
