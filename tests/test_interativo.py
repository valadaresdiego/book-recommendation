"""Embedding interativo das Obras do Leitor (SPEC §7.3) e o passo 2 do `atualizar` (§10)."""

import pytest
from codificador_falso import CodificadorDePalavras
from fabricas import criar_obra
from sqlalchemy import Connection, text

from recomendador.pipeline.conteudo import calcular_conteudo
from recomendador.pipeline.execucoes import ativar
from recomendador.pipeline.interativo import embeddings_pendentes, obras_pendentes
from recomendador.recomendacao.interativo import (
    ModeloDiferente,
    calcular_vizinhos_da_obra,
    modelo_de_conteudo_ativo,
    pendente,
)
from recomendador.recomendacao.texto import carregar_dados, hash_do_texto, texto_da_obra


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


# --- o embedding acompanha o texto da Obra ---


def test_guarda_o_hash_do_texto_que_virou_embedding(conexao, ativa) -> None:
    o = _obra_do_leitor(conexao, "Duna", "Frank Herbert", "desert planet spice")

    calcular_vizinhos_da_obra(conexao, o, CodificadorDePalavras(), k=3)

    guardado = conexao.execute(
        text("SELECT embedding_texto_hash FROM obra WHERE id = :o"), {"o": o}
    ).scalar_one()
    assert guardado == hash_do_texto(texto_da_obra(carregar_dados(conexao, [o])[o]))
    assert not pendente(conexao, o)


def test_obra_enriquecida_depois_do_embedding_fica_pendente(conexao, ativa) -> None:
    """O `atualizar` enriquece a Obra pela Open Library depois de salva: a descrição nova
    muda o texto, e o embedding e os Vizinhos têm de ser refeitos."""
    o = _obra_do_leitor(conexao, "Duna", "Ninguém", "village matchmaking")
    conexao.execute(text("UPDATE obra SET descricao = NULL WHERE id = :o"), {"o": o})
    cod = CodificadorDePalavras()
    calcular_vizinhos_da_obra(conexao, o, cod, k=3)
    assert obras_pendentes(conexao) == []

    conexao.execute(
        text("UPDATE obra SET descricao = 'desert planet spice' WHERE id = :o"), {"o": o}
    )

    assert pendente(conexao, o)
    assert obras_pendentes(conexao) == [o]
    assert embeddings_pendentes(conexao, cod) == 1
    assert _vizinhos(conexao, ativa, o)[0] in {"Dune", "Dune Messiah", "Children of Dune"}
    assert not pendente(conexao, o)


def test_assunto_novo_tambem_deixa_pendente(conexao, ativa) -> None:
    o = _obra_do_leitor(conexao, "Duna", "Frank Herbert", "desert planet spice")
    calcular_vizinhos_da_obra(conexao, o, CodificadorDePalavras(), k=3)

    conexao.execute(
        text("INSERT INTO obra_tag (obra_id, tag, contagem) VALUES (:o, 'ecology', 0)"),
        {"o": o},
    )

    assert pendente(conexao, o)


def test_embedding_copiado_de_uma_execucao_nova_fica_pendente(conexao, ativa, tmp_path) -> None:
    """O `ativar` copia o embedding do arquivo da execução, sem saber de que texto ele
    veio: a Obra do Leitor é refeita uma vez no próximo `atualizar`."""
    o = _obra_do_leitor(conexao, "Duna", "Frank Herbert", "desert planet spice")
    calcular_vizinhos_da_obra(conexao, o, CodificadorDePalavras(), k=3)
    nova = calcular_conteudo(conexao, CodificadorDePalavras(), tmp_path, k=3).execucao_id

    ativar(conexao, nova, tmp_path, forcar=True)

    linha = conexao.execute(
        text("SELECT embedding_execucao_id, embedding_texto_hash FROM obra WHERE id = :o"),
        {"o": o},
    ).one()
    assert tuple(linha) == (nova, None)
    assert obras_pendentes(conexao) == [o]


def test_so_as_obras_do_leitor_ficam_pendentes(conexao, ativa) -> None:
    """As da Base são refeitas pelo `recalcular`, não pelo `atualizar`."""
    conexao.execute(text("UPDATE obra SET descricao = 'outra coisa' WHERE origem = 'base'"))
    assert obras_pendentes(conexao) == []
