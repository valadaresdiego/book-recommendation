"""'Para você' (R4, SPEC §8.5) e página da Obra (R5, §8.3) sobre um Catálogo sintético."""

import numpy as np
import pytest
from fabricas import criar_obra
from sqlalchemy import Connection, text

from recomendador.config import LEITOR_ID, config
from recomendador.estante import adicionar, mudar_nota, remover
from recomendador.recomendacao import pagina_da_obra, para_voce
from recomendador.recomendacao.pontuacao import matriz_de_pesos, matriz_de_similaridade, pontuar

GRUPOS, POR_GRUPO = 4, 10


def _execucao(conexao: Connection, tipo: str, ativa: bool) -> int:
    return conexao.execute(
        text(
            "INSERT INTO execucao_modelo (tipo, modelo, ativa) VALUES (CAST(:t AS tipo_execucao), "
            "'teste', :a) RETURNING id"
        ),
        {"t": tipo, "a": ativa},
    ).scalar_one()


@pytest.fixture
def catalogo(conexao: Connection) -> dict:
    """40 Obras em 4 grupos de 10. Na execução de conteúdo ativa, cada Obra tem as 9 do
    grupo como Vizinhos (0,90 a 0,82) e 3 do grupo seguinte (0,20). Uma execução inativa
    liga tudo ao contrário, e não pode influir."""
    obras = [
        criar_obra(conexao, f"Obra {g}-{i}", (f"Autor {g}-{i}",), popularidade=1000 - 10 * g - i)
        for g in range(GRUPOS)
        for i in range(POR_GRUPO)
    ]
    grupo = {o: n // POR_GRUPO for n, o in enumerate(obras)}
    ativa = _execucao(conexao, "conteudo", True)
    inativa = _execucao(conexao, "conteudo", False)
    linhas = []
    for o in obras:
        mesmos = [v for v in obras if v != o and grupo[v] == grupo[o]]
        seguinte = [v for v in obras if grupo[v] == (grupo[o] + 1) % GRUPOS]
        i = obras.index(o) % POR_GRUPO
        outros = [seguinte[(i + 3 * k) % POR_GRUPO] for k in range(3)]
        vizinhos = [(v, 0.9 - 0.01 * k) for k, v in enumerate(mesmos)] + [(v, 0.2) for v in outros]
        for pos, (v, s) in enumerate(vizinhos, 1):
            linhas.append({"e": ativa, "o": o, "v": v, "s": s, "p": pos})
        for pos, v in enumerate(outros, 1):
            linhas.append({"e": inativa, "o": o, "v": v, "s": 0.99, "p": pos})
    conexao.execute(text("INSERT INTO vizinho VALUES (:e, :o, :v, :s, :p)"), linhas)
    return {"obras": obras, "grupo": grupo, "ativa": ativa}


def _ler(conexao: Connection, obra_id: int, nota: int | None) -> None:
    adicionar(conexao, LEITOR_ID, obra_id, nota, origem="manual")


# --- Para você ---


def test_com_5_notas_positivas_ha_ao_menos_10_sugestoes(conexao, catalogo) -> None:
    """O1 do PRD."""
    for o in catalogo["obras"][:5]:
        _ler(conexao, o, 5)

    r = para_voce(conexao, LEITOR_ID)

    assert r.suficiente and r.notas == 5
    assert len(r.sugestoes) >= 10


def test_menos_de_3_notas_pede_mais(conexao, catalogo) -> None:
    _ler(conexao, catalogo["obras"][0], 5)
    _ler(conexao, catalogo["obras"][1], 4)
    _ler(conexao, catalogo["obras"][2], None)  # sem Nota não conta

    r = para_voce(conexao, LEITOR_ID)

    assert (r.suficiente, r.notas, r.sugestoes) == (False, 2, [])


def test_nunca_sugere_obra_da_estante_e_motivo_tem_nota_alta(conexao, catalogo) -> None:
    obras = catalogo["obras"]
    for o, nota in zip(obras[:3], (5, 4, 1), strict=True):
        _ler(conexao, o, nota)
    _ler(conexao, obras[3], None)
    _ler(conexao, obras[12], 2)

    r = para_voce(conexao, LEITOR_ID)

    na_estante = {*obras[:4], obras[12]}
    assert r.sugestoes and not {s.obra_id for s in r.sugestoes} & na_estante
    assert all(s.motivo_nota >= 4 for s in r.sugestoes)
    assert all(s.pontuacao > 0 for s in r.sugestoes)
    pontos = [s.pontuacao for s in r.sugestoes]
    assert pontos == sorted(pontos, reverse=True)


def test_mudar_a_nota_de_5_para_1_derruba_as_sugestoes_dela(conexao, catalogo) -> None:
    """R2: a mudança aparece na próxima abertura, sem recálculo."""
    obras = catalogo["obras"]
    for o in (obras[0], obras[10], obras[20]):
        _ler(conexao, o, 5)
    antes = para_voce(conexao, LEITOR_ID)
    assert any(s.motivo_obra_id == obras[0] for s in antes.sugestoes)

    mudar_nota(conexao, LEITOR_ID, obras[0], 1)

    depois = para_voce(conexao, LEITOR_ID)
    assert not any(s.motivo_obra_id == obras[0] for s in depois.sugestoes)
    do_grupo_0 = {o for o in obras if catalogo["grupo"][o] == 0}
    assert not {s.obra_id for s in depois.sugestoes} & do_grupo_0


def test_remover_uma_leitura_devolve_a_obra_as_candidatas(conexao, catalogo) -> None:
    obras = catalogo["obras"]
    for o in obras[:4]:
        _ler(conexao, o, 5)
    assert obras[3] not in {s.obra_id for s in para_voce(conexao, LEITOR_ID).sugestoes}

    remover(conexao, LEITOR_ID, obras[3])

    assert obras[3] in {s.obra_id for s in para_voce(conexao, LEITOR_ID).sugestoes}


def test_sql_igual_a_pontuacao_da_avaliacao(conexao, catalogo, monkeypatch) -> None:
    """A consulta do 'Para você' e `recomendacao.pontuacao` (usada no §9) dão o mesmo, com
    conteúdo e Coleitura misturados por α, cada um dividido pela sua escala (ADR 0007), e o
    peso da popularidade (ADR 0006)."""
    monkeypatch.setattr(config(), "alfa", 0.25)
    monkeypatch.setattr(config(), "beta_popularidade", 0.25)
    obras = catalogo["obras"]
    coleitura = _execucao(conexao, "coleitura", True)
    linhas = [
        {"e": coleitura, "o": o, "v": obras[(n + d) % len(obras)], "s": 0.05 * d, "p": d}
        for n, o in enumerate(obras)
        for d in (1, 2, 3)
    ]
    conexao.execute(text("INSERT INTO vizinho VALUES (:e, :o, :v, :s, :p)"), linhas)
    for e, valor in ((catalogo["ativa"], 0.6), (coleitura, 0.1)):
        conexao.execute(
            text("UPDATE execucao_modelo SET parametros = CAST(:p AS jsonb) WHERE id = :e"),
            {"p": f'{{"escala": {valor}}}', "e": e},
        )
    estante = {obras[0]: 5, obras[11]: 4, obras[13]: 1, obras[25]: 2, obras[31]: 5}
    for o, nota in estante.items():
        _ler(conexao, o, nota)

    r = para_voce(conexao, LEITOR_ID, limite=40)

    def triplas(execucao: int) -> list:
        return conexao.execute(
            text("SELECT obra_id, vizinho_id, similaridade FROM vizinho WHERE execucao_id = :e"),
            {"e": execucao},
        ).all()

    indice = {o: i for i, o in enumerate(obras)}
    popularidade = np.array(
        [
            conexao.execute(text("SELECT popularidade FROM obra WHERE id = :o"), {"o": o}).scalar()
            for o in obras
        ]
    )
    s = matriz_de_similaridade(
        {"conteudo": triplas(catalogo["ativa"]), "coleitura": triplas(coleitura)},
        indice,
        alfa=0.25,
        escalas={"conteudo": 0.6, "coleitura": 0.1},
    )
    p = pontuar(matriz_de_pesos([estante], indice), s, popularidade, 0.25)[0]
    esperado = {o: float(p[i]) for o, i in indice.items() if p[i] > 0 and o not in estante}
    assert {s.obra_id: s.pontuacao for s in r.sugestoes} == pytest.approx(esperado, abs=1e-5)
    melhor = max(esperado, key=esperado.get)
    assert r.sugestoes[0].obra_id == melhor


# --- página da Obra ---


def test_pagina_da_obra_mostra_parecidos_e_quem_leu_vazio(conexao, catalogo) -> None:
    obras = catalogo["obras"]
    _ler(conexao, obras[1], 4)

    p = pagina_da_obra(conexao, obras[0], LEITOR_ID)

    assert p is not None and p.obra_id == obras[0] and p.nota is None
    assert [v.obra_id for v in p.parecidos] == obras[1:10] + [obras[10]]  # top 10
    assert [v.lido for v in p.parecidos][:2] == [True, False]
    assert p.quem_leu == []  # sem execução de coleitura ativa: R5b vazio


def test_pagina_da_obra_lida_traz_a_nota(conexao, catalogo) -> None:
    _ler(conexao, catalogo["obras"][0], 5)
    p = pagina_da_obra(conexao, catalogo["obras"][0], LEITOR_ID)
    assert p is not None and p.nota == 5 and p.na_estante


def test_pagina_de_obra_inexistente(conexao, catalogo) -> None:
    assert pagina_da_obra(conexao, 10**9, LEITOR_ID) is None
