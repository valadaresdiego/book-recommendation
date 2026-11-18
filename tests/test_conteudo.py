"""Similaridade de conteúdo: texto da Obra, Vizinhos em lote, execução e ativação (SPEC §8.2)."""

import json

import numpy as np
import pytest
from codificador_falso import CodificadorDePalavras
from fabricas import criar_genero, criar_obra, ligar_genero
from sqlalchemy import Connection, text

from recomendador.pipeline.conteudo import calcular_conteudo, top_vizinhos
from recomendador.pipeline.execucoes import AtivacaoRecusada, ativar
from recomendador.recomendacao.texto import DadosDaObra, carregar_dados, texto_da_obra

# --- texto_da_obra ---


def test_texto_da_obra_completo() -> None:
    dados = DadosDaObra(
        titulo="Dune",
        titulo_original="Dune",
        autores=("Frank Herbert",),
        generos=("Ficção científica",),
        tags=("science-fiction", "classics"),
        assuntos=("Science fiction", "Deserts"),
        descricao="Em Arrakis...",
    )
    assert texto_da_obra(dados) == (
        "Dune. Autor: Frank Herbert. Gêneros: Ficção científica. "
        "Temas: science fiction, classics, deserts. Em Arrakis..."
    )


def test_texto_da_obra_com_titulo_original_diferente_e_sem_extras() -> None:
    dados = DadosDaObra(titulo="Duna", titulo_original="Dune", autores=("Frank Herbert", "X"))
    assert texto_da_obra(dados) == "Duna (Dune). Autor: Frank Herbert, X."


def test_texto_da_obra_limita_tags_assuntos_e_descricao() -> None:
    dados = DadosDaObra(
        titulo="T",
        tags=tuple(f"tag-{i}" for i in range(20)),
        assuntos=tuple(f"assunto {i}" for i in range(20)),
        descricao="palavra " * 400,
    )
    texto = texto_da_obra(dados)
    temas = texto.split("Temas: ")[1].split(". ")[0].split(", ")
    assert temas[:15] == [f"tag {i}" for i in range(15)]
    assert temas[15:] == [f"assunto {i}" for i in range(10)]
    descricao = texto.split(". ", 2)[2]
    assert len(descricao) <= 1500
    assert descricao.endswith("palavra…")


# --- top_vizinhos ---


def test_top_vizinhos_exclui_a_propria_obra_e_ordena() -> None:
    e = np.array([[1, 0], [0.9, 0.1], [0, 1], [0.6, 0.8]], dtype=np.float32)
    e /= np.linalg.norm(e, axis=1, keepdims=True)

    viz = top_vizinhos(e, [None] * 4, k=2, max_mesmo_autor=5)

    assert [j for j, _ in viz[0]] == [1, 3]
    assert [j for j, _ in viz[2]] == [3, 1]
    assert viz[0][0][1] == pytest.approx(float(e[0] @ e[1]))


def test_top_vizinhos_limita_obras_do_mesmo_autor() -> None:
    """Uma série não domina a lista: no máximo `max_mesmo_autor` do autor da Obra."""
    rng = np.random.default_rng(0)
    base = rng.normal(size=8)
    e = np.stack([base + 0.01 * rng.normal(size=8) for _ in range(6)] + [rng.normal(size=8)])
    e /= np.linalg.norm(e, axis=1, keepdims=True)
    autores = ["herbert"] * 6 + ["outro"]

    viz = top_vizinhos(e, autores, k=4, max_mesmo_autor=2)

    vizinhos = [j for j, _ in viz[0]]
    assert len(vizinhos) == 3  # 2 de Herbert + a única Obra de outro autor
    assert sum(autores[j] == "herbert" for j in vizinhos) == 2
    assert 6 in vizinhos


# --- calcular-conteudo e ativar (banco real) ---


@pytest.fixture
def catalogo(conexao: Connection) -> dict[str, int]:
    ficcao = criar_genero(conexao, "ficcao-cientifica", "Ficção científica")
    ids = {
        "duna": criar_obra(conexao, "Dune", ("Frank Herbert",)),
        "messias": criar_obra(conexao, "Dune Messiah", ("Frank Herbert",)),
        "fundacao": criar_obra(conexao, "Foundation", ("Isaac Asimov",)),
        "orgulho": criar_obra(conexao, "Pride and Prejudice", ("Jane Austen",)),
    }
    for chave in ("duna", "messias", "fundacao"):
        ligar_genero(conexao, ids[chave], ficcao)
    descricoes = {
        "duna": "desert planet spice empire",
        "messias": "desert planet spice emperor",
        "fundacao": "galactic empire psychohistory",
        "orgulho": "marriage manners england",
    }
    for chave, d in descricoes.items():
        conexao.execute(
            text("UPDATE obra SET descricao = :d WHERE id = :o"), {"d": d, "o": ids[chave]}
        )
    conexao.execute(
        text("INSERT INTO obra_tag VALUES (:o, 'science-fiction', 10), (:o, 'arrakis', 0)"),
        {"o": ids["duna"]},
    )
    return ids


def test_carregar_dados(conexao: Connection, catalogo: dict[str, int]) -> None:
    dados = carregar_dados(conexao, [catalogo["duna"]])
    assert dados[catalogo["duna"]] == DadosDaObra(
        titulo="Dune",
        titulo_original=None,
        autores=("Frank Herbert",),
        generos=("Ficção científica",),
        tags=("science-fiction",),
        assuntos=("arrakis",),
        descricao="desert planet spice empire",
    )


def test_calcular_conteudo_cria_execucao_inativa_com_vizinhos(
    conexao: Connection, catalogo: dict[str, int], tmp_path
) -> None:
    resumo = calcular_conteudo(conexao, CodificadorDePalavras(), tmp_path, k=2)

    execucao = conexao.execute(
        text("SELECT tipo, modelo, ativa, parametros FROM execucao_modelo WHERE id = :e"),
        {"e": resumo.execucao_id},
    ).one()
    assert (str(execucao.tipo), execucao.modelo, execucao.ativa) == (
        "conteudo",
        "falso/palavras",
        False,
    )
    assert execucao.parametros["k"] == 2
    vizinhos = conexao.execute(
        text(
            "SELECT vizinho_id FROM vizinho WHERE execucao_id = :e AND obra_id = :o "
            "ORDER BY posicao"
        ),
        {"e": resumo.execucao_id, "o": catalogo["duna"]},
    ).scalars()
    assert list(vizinhos)[0] == catalogo["messias"]
    assert resumo.obras == 4 and resumo.vizinhos == 8
    assert (tmp_path / f"conteudo-{resumo.execucao_id}.npz").exists()
    # Nada muda em `obra.embedding` até a execução ser ativada.
    assert conexao.execute(text("SELECT count(embedding) FROM obra")).scalar_one() == 0


def test_ativar_copia_os_embeddings_e_deixa_uma_ativa(
    conexao: Connection, catalogo: dict[str, int], tmp_path
) -> None:
    primeira = calcular_conteudo(conexao, CodificadorDePalavras(), tmp_path, k=2).execucao_id
    segunda = calcular_conteudo(conexao, CodificadorDePalavras(), tmp_path, k=2).execucao_id

    ativar(conexao, primeira, tmp_path, forcar=True)
    ativar(conexao, segunda, tmp_path, forcar=True)

    ativas = conexao.execute(
        text("SELECT id FROM execucao_modelo WHERE ativa AND tipo = 'conteudo'")
    ).scalars()
    assert list(ativas) == [segunda]
    linhas = conexao.execute(text("SELECT embedding_execucao_id, embedding FROM obra")).all()
    assert {e for e, _ in linhas} == {segunda}
    assert all(np.isclose(np.linalg.norm(json.loads(v)), 1, atol=1e-3) for _, v in linhas)


def test_ativar_recusa_execucao_pior_que_a_ativa(
    conexao: Connection, catalogo: dict[str, int], tmp_path
) -> None:
    """SPEC §9.4: só entra se o NDCG@20 for ≥ ao da ativa do mesmo tipo."""
    ativa = calcular_conteudo(conexao, CodificadorDePalavras(), tmp_path, k=2).execucao_id
    nova = calcular_conteudo(conexao, CodificadorDePalavras(), tmp_path, k=2).execucao_id
    for execucao, ndcg in ((ativa, 0.20), (nova, 0.15)):
        conexao.execute(
            text("UPDATE execucao_modelo SET metricas = :m WHERE id = :e"),
            {"m": f'{{"ndcg@20": {ndcg}}}', "e": execucao},
        )
    ativar(conexao, ativa, tmp_path)

    with pytest.raises(AtivacaoRecusada, match="0,150"):
        ativar(conexao, nova, tmp_path)
    ativar(conexao, nova, tmp_path, forcar=True)


def test_ativar_sem_metricas_exige_forcar(
    conexao: Connection, catalogo: dict[str, int], tmp_path
) -> None:
    execucao = calcular_conteudo(conexao, CodificadorDePalavras(), tmp_path, k=2).execucao_id
    with pytest.raises(AtivacaoRecusada, match="avaliar"):
        ativar(conexao, execucao, tmp_path)
