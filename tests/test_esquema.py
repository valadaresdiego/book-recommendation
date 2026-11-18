"""O banco migrado bate com os modelos e cumpre as regras do SPEC §4."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from recomendador.config import LEITOR_ID
from recomendador.db.modelos import Base


def test_migracao_igual_aos_modelos(conexao: Connection) -> None:
    diferencas = compare_metadata(MigrationContext.configure(conexao), Base.metadata)
    assert diferencas == []


def test_leitor_unico_criado_pela_migracao(conexao: Connection) -> None:
    ids = conexao.execute(text("SELECT id FROM leitor")).scalars().all()
    assert ids == [LEITOR_ID]


def _obra(conexao: Connection, titulo: str = "Dune") -> int:
    return conexao.execute(
        text(
            "INSERT INTO obra (titulo, titulo_exibicao, origem) "
            "VALUES (:t, :t, 'leitor') RETURNING id"
        ),
        {"t": titulo},
    ).scalar_one()


def _leitura(conexao: Connection, obra_id: int, nota: int | None) -> None:
    conexao.execute(
        text(
            "INSERT INTO leitura (leitor_id, obra_id, nota, origem) VALUES (:l, :o, :n, 'manual')"
        ),
        {"l": LEITOR_ID, "o": obra_id, "n": nota},
    )


def test_mesma_obra_nao_entra_duas_vezes_na_estante(conexao: Connection) -> None:
    obra_id = _obra(conexao)
    _leitura(conexao, obra_id, 5)
    with pytest.raises(IntegrityError, match="leitura_uma_por_obra"):
        with conexao.begin_nested():
            _leitura(conexao, obra_id, 4)


@pytest.mark.parametrize("nota", [0, 6])
def test_nota_fora_de_1_a_5_e_recusada(conexao: Connection, nota: int) -> None:
    with pytest.raises(IntegrityError, match="leitura_nota_de_1_a_5"):
        with conexao.begin_nested():
            _leitura(conexao, _obra(conexao), nota)


def test_leitura_sem_nota_e_aceita(conexao: Connection) -> None:
    _leitura(conexao, _obra(conexao), None)


def test_no_maximo_uma_execucao_ativa_por_tipo(conexao: Connection) -> None:
    inserir = text("INSERT INTO execucao_modelo (tipo, modelo, ativa) VALUES (:tipo, 'x', :ativa)")
    conexao.execute(inserir, {"tipo": "conteudo", "ativa": True})
    conexao.execute(inserir, {"tipo": "conteudo", "ativa": False})
    conexao.execute(inserir, {"tipo": "coleitura", "ativa": True})
    with pytest.raises(IntegrityError, match="execucao_modelo_uma_ativa_por_tipo"):
        with conexao.begin_nested():
            conexao.execute(inserir, {"tipo": "conteudo", "ativa": True})


def test_embedding_tem_1024_dimensoes(conexao: Connection) -> None:
    obra_id = _obra(conexao)
    vetor = "[" + ",".join(["0.1"] * 1024) + "]"
    conexao.execute(
        text("UPDATE obra SET embedding = CAST(:v AS vector) WHERE id = :o"),
        {"v": vetor, "o": obra_id},
    )
    with pytest.raises(Exception, match="1024"):
        with conexao.begin_nested():
            conexao.execute(
                text("UPDATE obra SET embedding = CAST('[1,2,3]' AS vector) WHERE id = :o"),
                {"o": obra_id},
            )
