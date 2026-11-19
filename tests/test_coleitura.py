"""Coleitura (SPEC §8.1): cosseno ajustado com encolhimento, contra um cálculo à mão."""

import math

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import Connection, text

from recomendador.pipeline.coleitura import calcular_coleitura, vizinhos_de_coleitura
from tests.fabricas import criar_obra

# 4 leitores × 3 Obras. Médias: u1 = u2 = u3 = u4 = 4.
#        A   B   C            R (nota − média)
#   u1   5   5   2            1   1  −2
#   u2   4   5   3            0   1  −1
#   u3   5   4   3            1   0  −1
#   u4   ·   3   5            ·  −1   1
# ‖A‖ = √2, ‖B‖ = √3, ‖C‖ = √7
# num(A,B) = 1, n = 3 → única similaridade positiva
# num(A,C) = −3, num(B,C) = −4 → negativas, ficam fora
_NOTAS = pd.DataFrame(
    [
        ("u1", "A", 5), ("u1", "B", 5), ("u1", "C", 2),
        ("u2", "A", 4), ("u2", "B", 5), ("u2", "C", 3),
        ("u3", "A", 5), ("u3", "B", 4), ("u3", "C", 3),
        ("u4", "B", 3), ("u4", "C", 5),
    ],
    columns=["usuario_base", "obra_id", "nota"],
)  # fmt: skip
_INDICE = {"A": 0, "B": 1, "C": 2}


def test_cosseno_ajustado_com_encolhimento_contra_calculo_manual() -> None:
    vizinhos = vizinhos_de_coleitura(_NOTAS, _INDICE, k=10, lam=1, min_coleitores=1)

    esperado = 1 / (math.sqrt(2) * math.sqrt(3)) * 3 / (3 + 1)
    assert vizinhos[0] == [(1, pytest.approx(esperado))]
    assert vizinhos[1] == [(0, pytest.approx(esperado))]
    assert vizinhos[2] == []  # só similaridades negativas


def test_sem_encolhimento_e_o_cosseno_puro() -> None:
    vizinhos = vizinhos_de_coleitura(_NOTAS, _INDICE, k=10, lam=0, min_coleitores=1)
    assert vizinhos[0] == [(1, pytest.approx(1 / math.sqrt(6)))]


def test_par_com_poucos_coleitores_e_zerado() -> None:
    vizinhos = vizinhos_de_coleitura(_NOTAS, _INDICE, k=10, lam=1, min_coleitores=4)
    assert vizinhos == [[], [], []]  # A e B têm 3 coleitores


def test_top_k_em_ordem_sem_a_propria_obra() -> None:
    """Cinco leitores iguais em A, B e C (C com menos força) e um que discorda de C."""
    linhas = []
    for u in range(5):
        linhas += [(u, "A", 5), (u, "B", 5), (u, "C", 4), (u, "D", 1)]
    linhas += [(9, "A", 5), (9, "B", 5), (9, "C", 3), (9, "D", 1)]
    notas = pd.DataFrame(linhas, columns=["usuario_base", "obra_id", "nota"])
    indice = {"A": 0, "B": 1, "C": 2, "D": 3}

    todos = vizinhos_de_coleitura(notas, indice, k=10, lam=0, min_coleitores=1)
    um = vizinhos_de_coleitura(notas, indice, k=1, lam=0, min_coleitores=1)

    assert [j for j, _ in todos[0]] == [1, 2]  # B (idêntica a A) antes de C
    assert all(j != 0 for j, _ in todos[0])
    sims = [s for _, s in todos[0]]
    assert sims == sorted(sims, reverse=True) and all(s > 0 for s in sims)
    assert um[0] == todos[0][:1]


def test_leitor_que_da_a_mesma_nota_a_tudo_nao_soma() -> None:
    notas = pd.concat([_NOTAS, pd.DataFrame([("u5", o, 3) for o in "ABC"], columns=_NOTAS.columns)])
    com = vizinhos_de_coleitura(notas, _INDICE, k=10, lam=0, min_coleitores=1)
    sem = vizinhos_de_coleitura(_NOTAS, _INDICE, k=10, lam=0, min_coleitores=1)
    assert com == sem  # R = 0 em tudo; o encolhimento é que contaria u5 (λ = 0 aqui)


def test_calcular_coleitura_grava_execucao_inativa(conexao: Connection) -> None:
    obras = {nome: criar_obra(conexao, f"Obra {nome}") for nome in "ABC"}
    notas = _NOTAS.assign(obra_id=_NOTAS.obra_id.map(obras))

    r = calcular_coleitura(conexao, notas, k=10, lam=1, min_coleitores=1)

    execucao = conexao.execute(
        text("SELECT tipo::text, ativa, parametros FROM execucao_modelo WHERE id = :e"),
        {"e": r.execucao_id},
    ).one()
    assert execucao.tipo == "coleitura" and not execucao.ativa
    esperado = 1 / math.sqrt(6) * 3 / 4
    assert execucao.parametros == {
        "k": 10,
        "lambda": 1,
        "min_coleitores": 1,
        "escala": pytest.approx(esperado),  # a média dos Vizinhos gravados (ADR 0007)
    }
    vizinhos = conexao.execute(
        text(
            "SELECT obra_id, vizinho_id, similaridade, posicao FROM vizinho "
            "WHERE execucao_id = :e ORDER BY obra_id"
        ),
        {"e": r.execucao_id},
    ).all()
    assert [(v.obra_id, v.vizinho_id, v.posicao) for v in vizinhos] == [
        (obras["A"], obras["B"], 1),
        (obras["B"], obras["A"], 1),
    ]
    assert np.allclose([v.similaridade for v in vizinhos], esperado)
    assert r.vizinhos == 2 and r.obras == 3
