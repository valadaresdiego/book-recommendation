"""Capa de reserva para Obras sem `capa_url` (3.332 Obras da base vieram sem capa do goodbooks).

A reserva é um SVG gerado aqui mesmo, com título e autor, sem nenhuma requisição externa:
a Covers API da Open Library limita a busca por ISBN a 100 requisições por IP a cada 5 min,
o que não serve para encher uma grade de 24 capas.
"""

import hashlib
from html import escape
from textwrap import wrap

# Pares (fundo, texto) com contraste suficiente; a cor é fixa por título.
_PALETA = (
    ("#3d5a80", "#f4f1ea"),
    ("#6d597a", "#f4f1ea"),
    ("#386641", "#f4f1ea"),
    ("#9c6644", "#f4f1ea"),
    ("#264653", "#f4f1ea"),
    ("#8d2c3b", "#f4f1ea"),
)


def capa_reserva(titulo: str, autores: tuple[str, ...] | list[str] = ()) -> str:
    """Um SVG 2:3 com o título e o 1º autor, para `st.image` ou `<img>`."""
    fundo, cor = _PALETA[int(hashlib.md5(titulo.encode()).hexdigest(), 16) % len(_PALETA)]
    linhas = wrap(titulo, 14)[:5] or ["?"]
    texto = "".join(
        f'<tspan x="100" dy="{0 if i == 0 else 26}">{escape(linha)}</tspan>'
        for i, linha in enumerate(linhas)
    )
    autor = escape(autores[0]) if autores else ""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300" width="200" height="300">'
        f'<rect width="200" height="300" fill="{fundo}"/>'
        f'<rect x="12" y="12" width="176" height="276" fill="none" stroke="{cor}" '
        'stroke-opacity=".35"/>'
        f'<text x="100" y="{130 - 13 * (len(linhas) - 1)}" fill="{cor}" '
        f'font-family="Georgia,serif" font-size="22" text-anchor="middle">{texto}</text>'
        f'<text x="100" y="260" fill="{cor}" fill-opacity=".8" font-family="sans-serif" '
        f'font-size="13" text-anchor="middle">{autor[:28]}</text>'
        "</svg>"
    )


def capa(capa_url: str | None, titulo: str, autores: tuple[str, ...] | list[str] = ()) -> str:
    """A URL da capa, ou o SVG de reserva quando a Obra ou a Edição não tem capa."""
    return capa_url or capa_reserva(titulo, autores)
