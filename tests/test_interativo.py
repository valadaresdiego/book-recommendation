"""Embedding interativo das Obras do Leitor (SPEC §7.3) e o passo 2 do `atualizar` (§10)."""

import pytest
from codificador_falso import CodificadorDePalavras
from fabricas import criar_obra
from sqlalchemy import Connection, text

from recomendador.pipeline.conteudo import calcular_conteudo
from recomendador.pipeline.execucoes import ativar
from recomendador.pipeline.interativo import embeddings_pendentes
from recomendador.recomendacao.interativo import (
    ModeloDiferente,
    calcular_vizinhos_da_obra,
    modelo_de_conteudo_ativo,
)


@pytest.fixture
def ativa(conexao: Connection, tmp_path) -> int:
    """Um Catálogo da Base com a execução de conteúdo (codificador falso) ativa."""
    for titulo, autor, descricao in [
        ("Dune", "Frank Herbert", "desert planet spice"),
        ("Dune Messiah", "Frank Herbert", "desert planet spice emperor"),
        ("Children of Dune", "Frank Herbert", "desert planet spice twins"),
        ("Foundation", "Isaac Asimov", "galactic empire psychohistory"),
        ("Emma", "Jane Austen", "village matchmaking"),
    ]:
        o = criar_obra(conexao, titulo, (autor,))
        conexao.execute(
            text("UPDATE obra SET descricao = :d WHERE id = :o"), {"d": descricao, "o": o}
        )
    execucao = calcular_conteudo(conexao, CodificadorDePalavras(), tmp_path, k=3).execucao_id
    ativar(conexao, execucao, tmp_path, forcar=True)
    return execucao


def _obra_do_leitor(conexao: Connection, titulo: str, autor: str, descricao: str) -> int:
    o = criar_obra(conexao, titulo, (autor,), origem="leitor")
    conexao.execute(text("UPDATE obra SET descricao = :d WHERE id = :o"), {"d": descricao, "o": o})
    return o


def _vizinhos(conexao: Connection, execucao: int, obra: int) -> list[str]:
    return list(
        conexao.execute(
            text(
                "SELECT o.titulo FROM vizinho v JOIN obra o ON o.id = v.vizinho_id "
                "WHERE v.execucao_id = :e AND v.obra_id = :o ORDER BY v.posicao"
            ),
            {"e": execucao, "o": obra},
        ).scalars()
    )


def test_obra_do_leitor_ganha_embedding_e_vizinhos_da_base(conexao, ativa) -> None:
    duna = _obra_do_leitor(conexao, "Duna", "Frank Herbert", "desert planet spice Arrakis")

    n = calcular_vizinhos_da_obra(conexao, duna, CodificadorDePalavras(), k=3, max_mesmo_autor=2)

    assert n == 3
    vizinhos = _vizinhos(conexao, ativa, duna)
    assert vizinhos[0] == "Dune"
    assert sum(v.endswith("Dune") or v == "Dune Messiah" for v in vizinhos) == 2  # limite
    assert "Duna" not in vizinhos  # só Obras da Base
    linha = conexao.execute(
        text("SELECT embedding IS NOT NULL, embedding_execucao_id FROM obra WHERE id = :o"),
        {"o": duna},
    ).one()
    assert tuple(linha) == (True, ativa)


def test_recalcular_troca_os_vizinhos(conexao, ativa) -> None:
    o = _obra_do_leitor(conexao, "X", "Ninguém", "desert planet spice")
    cod = CodificadorDePalavras()
    calcular_vizinhos_da_obra(conexao, o, cod, k=3)
    calcular_vizinhos_da_obra(conexao, o, cod, k=3)
    assert len(_vizinhos(conexao, ativa, o)) == 3


def test_modelo_diferente_do_ativo_e_recusado(conexao, ativa) -> None:
    o = _obra_do_leitor(conexao, "X", "Ninguém", "y")

    class Outro(CodificadorDePalavras):
        nome = "outro/modelo"

    assert modelo_de_conteudo_ativo(conexao) == "falso/palavras"
    with pytest.raises(ModeloDiferente):
        calcular_vizinhos_da_obra(conexao, o, Outro())


def test_sem_execucao_ativa_nao_calcula(conexao) -> None:
    o = _obra_do_leitor(conexao, "X", "Ninguém", "y")
    assert modelo_de_conteudo_ativo(conexao) is None
    assert calcular_vizinhos_da_obra(conexao, o, CodificadorDePalavras()) == 0


def test_atualizar_calcula_as_obras_do_leitor_pendentes(conexao, ativa) -> None:
    pendentes = [
        _obra_do_leitor(conexao, f"Livro {i}", "Alguém", "desert planet spice") for i in range(3)
    ]

    feitas = embeddings_pendentes(conexao, CodificadorDePalavras())

    assert feitas == 3
    assert all(_vizinhos(conexao, ativa, o) for o in pendentes)
    assert embeddings_pendentes(conexao, CodificadorDePalavras()) == 0
