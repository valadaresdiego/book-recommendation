"""Um codificador de texto sem modelo, para testar o pipeline de conteúdo sem GPU."""

import hashlib
import re
from collections.abc import Sequence

import numpy as np

from recomendador.db.modelos import DIMENSAO_EMBEDDING


class CodificadorDePalavras:
    """Saco de palavras com hash: textos com palavras em comum ficam próximos."""

    nome = "falso/palavras"

    def codificar(self, textos: Sequence[str]) -> np.ndarray:
        saida = np.zeros((len(textos), DIMENSAO_EMBEDDING), dtype=np.float32)
        for i, t in enumerate(textos):
            for palavra in re.findall(r"\w+", t.lower()):
                h = int.from_bytes(hashlib.md5(palavra.encode()).digest()[:4], "little")
                saida[i, h % DIMENSAO_EMBEDDING] += 1.0
        normas = np.linalg.norm(saida, axis=1, keepdims=True)
        return saida / np.where(normas == 0, 1, normas)
