"""A pontuação de "Para você" (SPEC §8.5) em matrizes esparsas.

    soma(c)      = Σ_r peso(nota_r) × [ α·sim_conteudo(r→c)/escala_conteudo
                                    + (1−α)·sim_coleitura(r→c)/escala_coleitura ]
    pontuacao(c) = soma(c) × (1 + popularidade(c))^β            (ADR 0006)

A escala de cada execução é a média das similaridades dos Vizinhos dela (ADR 0007): sem
ela, o conteúdo (~0,55) engoliria a Coleitura (~0,07) em qualquer α.

Com W (Estantes × Obras, os pesos das Notas) e S (Obras × Obras, as similaridades já
misturadas por α), a pontuação de todas as Estantes é `W @ S`. A avaliação offline (§9)
usa estas funções; `para_voce` faz a mesma conta em SQL, e um teste confere as duas.
"""

from collections.abc import Hashable, Iterable, Mapping, Sequence

import numpy as np
from scipy import sparse

from recomendador.config import PESO_DA_NOTA


def escala(similaridades: Iterable[float]) -> float:
    """A média das similaridades dos Vizinhos de uma execução (1 se não houver nenhum).
    Fica em `execucao_modelo.parametros.escala` (ADR 0007)."""
    valores = np.fromiter(similaridades, dtype=np.float64)
    return float(valores.mean()) if len(valores) and valores.mean() > 0 else 1.0


def matriz_de_similaridade[K: Hashable](
    vizinhos: Mapping[str, Iterable[tuple[K, K, float]]],
    indice: Mapping[K, int],
    alfa: float,
    escalas: Mapping[str, float] | None = None,
) -> sparse.csr_matrix:
    """S[r, c] = α·sim_conteudo(r→c)/escala_conteudo + (1−α)·sim_coleitura(r→c)/escala_coleitura;
    ausente vale 0.

    `vizinhos` traz, por tipo ('conteudo', 'coleitura'), as triplas (Obra, Vizinho, sim);
    `escalas`, a escala de cada tipo (1 se faltar).
    """
    escalas = escalas or {}
    fator = {
        "conteudo": alfa / escalas.get("conteudo", 1.0),
        "coleitura": (1 - alfa) / escalas.get("coleitura", 1.0),
    }
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
    estantes: Sequence[Mapping[K, int | None]],
    indice: Mapping[K, int],
    pesos: Mapping[int, float] = PESO_DA_NOTA,
) -> sparse.csr_matrix:
    """W[e, r] = peso(nota de r na Estante e). Leituras sem Nota ou de peso 0 ficam fora.

    `pesos` é a tabela Nota → peso; a do PRD (`config.PESO_DA_NOTA`) é a do app, e a
    avaliação compara outras (SPEC §9.4)."""
    linhas: list[int] = []
    colunas: list[int] = []
    valores: list[float] = []
    for e, estante in enumerate(estantes):
        for obra, nota in estante.items():
            if nota is None or obra not in indice or not (peso := pesos[nota]):
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
