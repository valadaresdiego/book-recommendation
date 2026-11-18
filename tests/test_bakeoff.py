"""Teste entre idiomas do bake-off (SPEC §8.4)."""

import numpy as np
from codificador_falso import CodificadorDePalavras

from recomendador.pipeline.bakeoff import Par, carregar_pares, conferir_entre_idiomas, gravar_pares


def test_teste_entre_idiomas_acha_a_propria_obra_entre_as_3_primeiras() -> None:
    cod = CodificadorDePalavras()
    catalogo = {
        10: "Dune. Autor: Frank Herbert. Arrakis spice desert Atreides",
        11: "Foundation. Autor: Isaac Asimov. Seldon psychohistory empire",
        12: "Emma. Autor: Jane Austen. Highbury matchmaking",
        13: "Persuasion. Autor: Jane Austen. Anne Elliot navy",
        14: "Kindred. Autor: Octavia Butler. Dana slavery time",
    }
    ids = np.array(list(catalogo))
    e = cod.codificar(list(catalogo.values()))
    pares = [
        Par(1, "x", "v1", "Duna", ("Frank Herbert",), "Arrakis Atreides especiaria deserto"),
        Par(2, "y", "v2", "Fundação", ("Isaac Asimov",), "Seldon psico-história império"),
        Par(3, "z", "v3", "Kindred", ("Octavia Butler",), "palavras sem nada em comum"),
    ]

    r = conferir_entre_idiomas(cod, pares, {1: 10, 2: 11, 3: 12}, ids, e, top=1)

    assert r.posicoes == {1: 1, 2: 1, 3: None}  # 3 aponta para Emma: não acha
    assert (r.acertos, r.total, r.resumo()) == (2, 3, "2/3")


def test_pares_guardam_so_identificadores_no_yaml(tmp_path) -> None:
    pares = [Par(1, "9788576573135", "co7YzgEACAAJ", "Duna", ("Frank Herbert",), "Texto.")]
    yaml_, cache = tmp_path / "pares.yaml", tmp_path / "cache" / "pares.json"

    gravar_pares(pares, yaml_, cache)

    assert "Texto." not in yaml_.read_text(encoding="utf-8")
    assert carregar_pares(yaml_, cache, google=None) == pares
