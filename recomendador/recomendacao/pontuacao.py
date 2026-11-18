"""A pontuação de "Para você" (SPEC §8.5) em matrizes esparsas.

    soma(c)      = Σ_r peso(nota_r) × [ α·sim_conteudo(r→c) + (1−α)·sim_coleitura(r→c) ]
    pontuacao(c) = soma(c) × (1 + popularidade(c))^β            (ADR 0006)

Com W (Estantes × Obras, os pesos das Notas) e S (Obras × Obras, as similaridades já
misturadas por α), a pontuação de todas as Estantes é `W @ S`. A avaliação offline (§9)
usa estas funções; `para_voce` faz a mesma conta em SQL, e um teste confere as duas.
"""

from collections.abc import Hashable, Iterable, Mapping, Sequence

import numpy as np
from scipy import sparse

from recomendador.config import PESO_DA_NOTA


def matriz_de_similaridade[K: Hashable](
    vizinhos: Mapping[str, Iterable[tuple[K, K, float]]],
    indice: Mapping[K, int],
    alfa: float,
) -> sparse.csr_matrix:
    """S[r, c] = α·sim_conteudo(r→c) + (1−α)·sim_coleitura(r→c); ausente vale 0.

    `vizinhos` traz, por tipo ('conteudo', 'coleitura'), as triplas (Obra, Vizinho, sim).
    """
    fator = {"conteudo": alfa, "coleitura": 1 - alfa}
    linhas: list[int] = []
    colunas: list[int] = []
    valores: list[float] = []
    for tipo, triplas in vizinhos.items():
        if (f := fator[tipo]) == 0:
            continue
        for obra, vizinho, sim in triplas:
            if obra in indice and vizinho in indice:
                linhas.append(indice[obra])
                colunas.append(indice[vizinho])
                valores.append(f * sim)
    n = len(indice)
    return sparse.csr_matrix((np.array(valores, dtype=np.float32), (linhas, colunas)), shape=(n, n))


def matriz_de_pesos[K: Hashable](
    estantes: Sequence[Mapping[K, int | None]], indice: Mapping[K, int]
) -> sparse.csr_matrix:
    """W[e, r] = peso(nota de r na Estante e). Leituras sem Nota ou de peso 0 ficam fora."""
    linhas: list[int] = []
    colunas: list[int] = []
    valores: list[float] = []
    for e, estante in enumerate(estantes):
        for obra, nota in estante.items():
            if nota is None or obra not in indice or not (peso := PESO_DA_NOTA[nota]):
                continue
            linhas.append(e)
            colunas.append(indice[obra])
            valores.append(peso)
    return sparse.csr_matrix(
        (np.array(valores, dtype=np.float32), (linhas, colunas)),
        shape=(len(estantes), len(indice)),
    )


def pontuar(
    pesos: sparse.csr_matrix,
    similaridade: sparse.csr_matrix,
    popularidade: np.ndarray | None = None,
    beta: float = 0.0,
) -> np.ndarray:
    """A pontuação de cada Obra para cada Estante (linhas de `pesos`), densa.

    Com `beta` > 0, a soma é multiplicada por (1 + popularidade)^β (ADR 0006). O fator é
    positivo: o sinal da soma, e portanto quem é candidata, não muda.
    """
    soma = np.asarray((pesos @ similaridade).todense(), dtype=np.float64)
    if beta and popularidade is not None:
        soma *= (1.0 + popularidade.astype(np.float64)) ** beta
    return soma
