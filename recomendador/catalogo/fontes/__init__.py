"""Clientes HTTP externos (Google Books, Open Library). Únicos lugares com chamadas de rede."""


class FonteIndisponivel(Exception):
    """A fonte externa não respondeu a tempo ou respondeu com erro (rede, 5xx, 429)."""
