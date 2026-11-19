"""Avaliação offline (SPEC §9) e a pontuação do §8.5 em matrizes."""

import math

import numpy as np
import pandas as pd
import pytest
from scipy import sparse
from sqlalchemy import Connection, text

from recomendador.pipeline.avaliacao import (
    TABELAS_DE_PESO,
    VARREDURA_ALFA,
    VARREDURA_BETA,
    VARREDURA_K,
    VARREDURA_LAMBDA,
    Divisao,
    avaliar,
    dividir,
    ndcg,
    notas_de_treino,
    recall,
    top_n,
)
from recomendador.recomendacao.pontuacao import (
    escala,
    matriz_de_pesos,
    matriz_de_similaridade,
    pontuar,
)

# --- métricas ---


def test_ndcg_contra_valor_conhecido() -> None:
    # Acerto na posição 2 de 2 relevantes: DCG = 1/log2(3); IDCG = 1 + 1/log2(3).
    esperado = (1 / math.log2(3)) / (1 + 1 / math.log2(3))
    assert ndcg([10, 20, 30], {20, 40}) == pytest.approx(esperado)
    assert ndcg([20, 40], {20, 40}) == pytest.approx(1.0)
    assert ndcg([1, 2], {3}) == 0.0


def test_recall() -> None:
    assert recall([10, 20, 30], {20, 40}) == 0.5
    assert recall([], {1}) == 0.0


# --- pontuação ---


def test_pontuar_soma_peso_vezes_similaridade() -> None:
    """Leituras A (5) e B (1); A→C 0,8, B→C 0,5, A→D 0,4.
    C = 1,0·0,8 − 1,0·0,5 = 0,3; D = 1,0·0,4 = 0,4."""
    indice = {"A": 0, "B": 1, "C": 2, "D": 3}
    s = matriz_de_similaridade(
        {"conteudo": [("A", "C", 0.8), ("B", "C", 0.5), ("A", "D", 0.4)]}, indice, alfa=1.0
    )
    w = matriz_de_pesos([{"A": 5, "B": 1}], indice)

    p = pontuar(w, s)

    assert p[0].tolist() == pytest.approx([0.0, 0.0, 0.3, 0.4])


def test_alfa_mistura_conteudo_e_coleitura() -> None:
    indice = {"A": 0, "C": 1}
    vizinhos = {"conteudo": [("A", "C", 0.8)], "coleitura": [("A", "C", 0.2)]}
    s = matriz_de_similaridade(vizinhos, indice, alfa=0.25)
    assert s[0, 1] == pytest.approx(0.25 * 0.8 + 0.75 * 0.2)


def test_escalas_igualam_conteudo_e_coleitura() -> None:
    """ADR 0007: cada tipo é dividido pela sua escala antes da mistura."""
    indice = {"A": 0, "C": 1}
    vizinhos = {"conteudo": [("A", "C", 0.6)], "coleitura": [("A", "C", 0.05)]}
    s = matriz_de_similaridade(
        vizinhos, indice, alfa=0.25, escalas={"conteudo": 0.6, "coleitura": 0.1}
    )
    assert s[0, 1] == pytest.approx(0.25 * 1.0 + 0.75 * 0.5)
    assert escala([0.2, 0.4]) == pytest.approx(0.3)
    assert escala([]) == 1.0


def test_top_n_tira_o_treino_e_desempata_pela_popularidade() -> None:
    pontos = np.array([[0.5, 0.9, 0.5, 0.0, 0.5]])
    popularidade = np.array([1, 1, 3, 9, 2])
    treino = sparse.csr_matrix(np.array([[0, 1, 0, 0, 0]]))
    assert top_n(pontos, treino, popularidade, n=3) == [[2, 4, 0]]  # 3 tem pontuação 0


def test_top_n_por_linha_com_menos_candidatas_que_n() -> None:
    pontos = np.array([[0.1, 0.0, 0.3, 0.2], [0.0, 0.0, 0.0, 0.0], [0.4, 0.4, 0.1, 0.0]])
    popularidade = np.array([5, 1, 2, 3])
    treino = sparse.csr_matrix(np.array([[0, 0, 1, 0], [0, 0, 0, 0], [0, 0, 0, 0]]))
    assert top_n(pontos, treino, popularidade, n=3) == [[3, 0], [], [0, 1, 2]]


def test_tabela_de_pesos_simetrica() -> None:
    indice = {"A": 0, "B": 1}
    w = matriz_de_pesos([{"A": 4, "B": 2}], indice, TABELAS_DE_PESO["simetrica"])
    assert w.toarray().tolist() == [[0.5, -0.5]]


# --- divisão ---


def _notas(leitores: int, por_leitor: int, semente: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(semente)
    linhas = [
        (u, o, int(rng.integers(1, 6)))
        for u in range(leitores)
        for o in rng.choice(100, size=por_leitor, replace=False)
    ]
    return pd.DataFrame(linhas, columns=["usuario_base", "obra_id", "nota"])


def test_divisao_reprodutivel_e_sem_vazamento() -> None:
    notas = pd.concat(
        [
            _notas(30, 25),
            _notas(5, 10, semente=2).assign(usuario_base=lambda d: d.usuario_base + 100),
        ]
    )

    d1 = dividir(notas, n_leitores=20, min_notas=20, frac_teste=0.2, semente=42)
    d2 = dividir(notas, n_leitores=20, min_notas=20, frac_teste=0.2, semente=42)

    assert d1.leitores == d2.leitores
    assert len(d1.leitores) == 20
    assert all(u < 100 for u in d1.leitores)  # só quem tem ≥ 20 Notas
    for u in d1.leitores:
        treino, teste = d1.treino[u], d1.teste[u]
        assert not set(treino) & teste
        minhas = notas[notas.usuario_base == u]
        boas = set(minhas[minhas.nota >= 4].obra_id)
        assert teste <= boas
        assert len(teste) == max(1, round(0.2 * len(boas)))
        assert set(treino) | teste == set(minhas.obra_id)


def test_notas_de_treino_tira_so_as_de_teste() -> None:
    notas = _notas(30, 25)
    divisao = dividir(notas, n_leitores=10, min_notas=20, semente=42)

    treino = notas_de_treino(notas, divisao)

    pares = set(zip(treino.usuario_base, treino.obra_id, strict=True))
    teste = {(u, o) for u, obras in divisao.teste.items() for o in obras}
    assert not pares & teste
    assert len(treino) == len(notas) - len(teste)


# --- avaliar (banco real) ---


def _catalogo_em_grupos(conexao: Connection) -> tuple[list[int], int, pd.DataFrame]:
    """20 grupos de 10 Obras; cada leitor gosta de um grupo só e dá Nota baixa a Obras
    soltas de outros. Os Vizinhos de conteúdo ligam as Obras do mesmo grupo."""
    ids = [
        conexao.execute(
            text(
                "INSERT INTO obra (titulo, titulo_exibicao, origem, popularidade) "
                "VALUES (:t, :t, 'base', :p) RETURNING id"
            ),
            {"t": f"Obra {i}", "p": 1000 - i},
        ).scalar_one()
        for i in range(200)
    ]
    grupo = {o: i // 10 for i, o in enumerate(ids)}
    execucao = conexao.execute(
        text("INSERT INTO execucao_modelo (tipo, modelo) VALUES ('conteudo', 'x') RETURNING id")
    ).scalar_one()
    for o in ids:
        mesmos = [v for v in ids if v != o and grupo[v] == grupo[o]]
        for pos, v in enumerate(mesmos, 1):
            conexao.execute(
                text("INSERT INTO vizinho VALUES (:e, :o, :v, :s, :p)"),
                {"e": execucao, "o": o, "v": v, "s": 1 - pos / 100, "p": pos},
            )
    rng = np.random.default_rng(0)
    linhas = []
    for u in range(60):
        g = u % 20
        do_grupo = [o for o in ids if grupo[o] == g]
        outras = [o for o in ids if grupo[o] != g]
        linhas += [(u, o, 5) for o in rng.choice(do_grupo, size=8, replace=False)]
        linhas += [(u, o, 2) for o in rng.choice(outras, size=16, replace=False)]
    notas = pd.DataFrame(linhas, columns=["usuario_base", "obra_id", "nota"])
    return ids, execucao, notas


def test_avaliar_grava_metricas_e_compara_com_a_popularidade(conexao: Connection, tmp_path) -> None:
    """O conteúdo liga as Obras do mesmo grupo e acerta mais que a popularidade."""
    _, execucao, notas = _catalogo_em_grupos(conexao)
    divisao = dividir(notas, n_leitores=50, min_notas=20, frac_teste=0.2, semente=42)
    assert isinstance(divisao, Divisao)

    conexao.execute(
        text(
            """UPDATE execucao_modelo SET metricas = '{"entre_idiomas": "19/20"}' WHERE id = :e"""
        ),
        {"e": execucao},
    )

    resultado = avaliar(conexao, [execucao], divisao, pasta_relatorios=tmp_path)

    m = resultado.metricas[execucao]
    assert m["ndcg@20"] > resultado.popularidade["ndcg@20"]
    assert 0 < m["recall@20"] <= 1 and 0 < m["cobertura"] <= 1
    assert m["leitores"] == 50
    gravadas = conexao.execute(
        text("SELECT metricas FROM execucao_modelo WHERE id = :e"), {"e": execucao}
    ).scalar_one()
    assert gravadas["ndcg@20"] == pytest.approx(m["ndcg@20"])
    assert gravadas["entre_idiomas"] == "19/20"  # métricas de antes ficam
    relatorio = resultado.relatorio.read_text(encoding="utf-8")
    assert "Popularidade" in relatorio and f"| {execucao} |" in relatorio


def test_beta_multiplica_pela_popularidade_sem_mudar_o_sinal() -> None:
    indice = {"A": 0, "B": 1, "C": 2}
    s = matriz_de_similaridade({"conteudo": [("A", "B", 0.5), ("A", "C", 0.5)]}, indice, 1.0)
    w = matriz_de_pesos([{"A": 5}], indice)
    popularidade = np.array([0, 3, 15])

    p = pontuar(w, s, popularidade, beta=0.5)

    assert p[0].tolist() == pytest.approx([0.0, 0.5 * 2, 0.5 * 4])
    negativo = pontuar(matriz_de_pesos([{"A": 1}], indice), s, popularidade, beta=0.5)
    assert (negativo[0, 1:] < 0).all()


def _coleitura_sem_vizinhos(conexao: Connection) -> int:
    """Uma execução de Coleitura sem nada em `vizinho`: a avaliação tem de recalcular."""
    return conexao.execute(
        text(
            "INSERT INTO execucao_modelo (tipo, modelo, parametros) VALUES ('coleitura', "
            """'cosseno-ajustado', '{"k": 50, "lambda": 10, "min_coleitores": 1}') RETURNING id"""
        )
    ).scalar_one()


def test_coleitura_e_recalculada_no_treino(conexao: Connection, tmp_path) -> None:
    _, _, notas = _catalogo_em_grupos(conexao)
    coleitura = _coleitura_sem_vizinhos(conexao)
    divisao = dividir(notas, n_leitores=50, min_notas=20, semente=42)

    with pytest.raises(ValueError, match="notas"):
        avaliar(conexao, [coleitura], divisao, tmp_path)
    r = avaliar(conexao, [coleitura], divisao, tmp_path, notas=notas)

    assert r.metricas[coleitura]["ndcg@20"] > r.popularidade["ndcg@20"]


def test_combinacao_e_varredura(conexao: Connection, tmp_path) -> None:
    _, conteudo, notas = _catalogo_em_grupos(conexao)
    coleitura = _coleitura_sem_vizinhos(conexao)
    divisao = dividir(notas, n_leitores=50, min_notas=20, semente=42)

    r = avaliar(
        conexao, [conteudo, coleitura], divisao, tmp_path, notas=notas,
        combinar=(conteudo, coleitura),
    )  # fmt: skip

    assert r.combinada is not None
    assert r.combinada["conteudo"] == conteudo and r.combinada["coleitura"] == coleitura
    for e in (conteudo, coleitura):
        assert r.metricas[e]["combinada"]["ndcg@20"] == pytest.approx(r.combinada["ndcg@20"])
        assert "ndcg@20" in r.metricas[e]  # a isolada continua lá
    por_tabela = 1 + (len(VARREDURA_ALFA) - 1) * len(VARREDURA_K) * len(VARREDURA_LAMBDA)
    assert len(r.varredura) == len(TABELAS_DE_PESO) * len(VARREDURA_BETA) * por_tabela
    assert r.combinada["melhor"]["ndcg@20"] == max(x["ndcg@20"] for x in r.varredura)
    so_conteudo = [x for x in r.varredura if x["alfa"] == 1]
    assert all(x["k"] is None and x["lambda"] is None for x in so_conteudo)
    relatorio = r.relatorio.read_text(encoding="utf-8")
    assert "## Combinação" in relatorio and "Critério do §14" in relatorio
    assert list(tmp_path.glob("varredura-*.csv"))


def test_combinar_confere_os_tipos(conexao: Connection, tmp_path) -> None:
    _, conteudo, notas = _catalogo_em_grupos(conexao)
    coleitura = _coleitura_sem_vizinhos(conexao)
    divisao = dividir(notas, n_leitores=50, min_notas=20, semente=42)
    with pytest.raises(ValueError, match="combinar"):
        avaliar(conexao, [], divisao, tmp_path, notas=notas, combinar=(coleitura, conteudo))
