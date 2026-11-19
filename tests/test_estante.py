"""Estante (R1 a R3), Eventos (SPEC §7.6) e Montagem da Estante (SPEC §7.4)."""

import pytest
from fabricas import criar_genero, criar_obra, ligar_genero
from sqlalchemy import Connection, text

from recomendador.config import LEITOR_ID
from recomendador.estante import (
    JaNaEstante,
    adicionar,
    contar_notas,
    grade_da_montagem,
    leitura_da_obra,
    listar,
    montagem_pendente,
    mudar_nota,
    pular_montagem,
    registrar_evento,
    remover,
)


def _eventos(conexao: Connection, tipo: str) -> list[dict]:
    return [
        {"obra_id": o, **d}
        for o, d in conexao.execute(
            text("SELECT obra_id, dados FROM evento WHERE tipo = :t ORDER BY id"), {"t": tipo}
        )
    ]


def _leituras(conexao: Connection) -> int:
    return conexao.execute(text("SELECT count(*) FROM leitura")).scalar_one()


@pytest.fixture
def duna(conexao: Connection) -> int:
    return criar_obra(conexao, "Dune", ("Frank Herbert",), titulo_exibicao="Duna")


# --- Adicionar (R1 + R2) ---


def test_adicionar_grava_a_leitura_e_o_evento(conexao: Connection, duna: int) -> None:
    leitura = adicionar(conexao, LEITOR_ID, duna, 5, origem="busca", duracao_s=12.5)

    assert (leitura.obra_id, leitura.nota, leitura.origem) == (duna, 5, "busca")
    assert _eventos(conexao, "leitura_salva") == [
        {"obra_id": duna, "origem": "busca", "duracao_s": 12.5, "com_nota": True}
    ]


def test_mesma_obra_por_outra_edicao_avisa_e_nao_duplica(conexao: Connection, duna: int) -> None:
    adicionar(conexao, LEITOR_ID, duna, 5, origem="busca")
    edicao = conexao.execute(
        text("INSERT INTO edicao (obra_id, titulo) VALUES (:o, 'Duna') RETURNING id"), {"o": duna}
    ).scalar_one()

    with pytest.raises(JaNaEstante) as erro:
        adicionar(conexao, LEITOR_ID, duna, 3, origem="busca", edicao_id=edicao)

    assert str(erro.value) == "Você já tem Duna na Estante, com nota 5"
    assert erro.value.item.nota == 5
    assert _leituras(conexao) == 1
    assert len(_eventos(conexao, "leitura_salva")) == 1


def test_aviso_de_obra_ja_na_estante_sem_nota(conexao: Connection, duna: int) -> None:
    adicionar(conexao, LEITOR_ID, duna, None, origem="manual")
    with pytest.raises(JaNaEstante, match="^Você já tem Duna na Estante, sem nota$"):
        adicionar(conexao, LEITOR_ID, duna, 4, origem="manual")


def test_leitura_sem_nota_fica_na_estante_mas_nao_conta(conexao: Connection, duna: int) -> None:
    adicionar(conexao, LEITOR_ID, duna, None, origem="busca")

    assert [i.obra_id for i in listar(conexao, LEITOR_ID)] == [duna]
    assert contar_notas(conexao, LEITOR_ID) == 0
    assert _eventos(conexao, "leitura_salva")[0]["com_nota"] is False


@pytest.mark.parametrize("nota", [0, 6])
def test_nota_fora_de_1_a_5(conexao: Connection, duna: int, nota: int) -> None:
    with pytest.raises(ValueError, match="de 1 a 5"):
        adicionar(conexao, LEITOR_ID, duna, nota, origem="busca")


# --- Mudar Nota e remover (R2) ---


def test_mudar_nota(conexao: Connection, duna: int) -> None:
    adicionar(conexao, LEITOR_ID, duna, 5, origem="busca")

    mudar_nota(conexao, LEITOR_ID, duna, 1)

    assert leitura_da_obra(conexao, LEITOR_ID, duna).nota == 1
    assert _eventos(conexao, "nota_alterada") == [{"obra_id": duna, "de": 5, "para": 1}]


def test_mudar_para_a_mesma_nota_nao_registra_evento(conexao: Connection, duna: int) -> None:
    adicionar(conexao, LEITOR_ID, duna, 4, origem="busca")
    mudar_nota(conexao, LEITOR_ID, duna, 4)
    assert _eventos(conexao, "nota_alterada") == []


def test_remover(conexao: Connection, duna: int) -> None:
    adicionar(conexao, LEITOR_ID, duna, 2, origem="busca")

    remover(conexao, LEITOR_ID, duna)

    assert leitura_da_obra(conexao, LEITOR_ID, duna) is None
    assert _eventos(conexao, "leitura_removida") == [{"obra_id": duna, "nota": 2}]
    # Pode voltar à Estante depois.
    adicionar(conexao, LEITOR_ID, duna, 4, origem="busca")


# --- Estante (R3) ---


def test_estante_ordena_por_nota_ou_por_data(conexao: Connection) -> None:
    a = criar_obra(conexao, "A", ("X",))
    b = criar_obra(conexao, "B", ("Y",))
    c = criar_obra(conexao, "C", ("Z",))
    for obra, nota, quando in [(a, 3, "1 day"), (b, None, "2 days"), (c, 5, "3 days")]:
        adicionar(conexao, LEITOR_ID, obra, nota, origem="busca")
        conexao.execute(
            text("UPDATE leitura SET criado_em = now() - CAST(:q AS interval) WHERE obra_id = :o"),
            {"q": quando, "o": obra},
        )

    assert [i.obra_id for i in listar(conexao, LEITOR_ID, ordem="nota")] == [c, a, b]
    assert [i.obra_id for i in listar(conexao, LEITOR_ID, ordem="data")] == [a, b, c]


def test_item_da_estante_usa_a_capa_da_edicao_escolhida(conexao: Connection) -> None:
    obra = criar_obra(conexao, "Dune", ("Frank Herbert",), capa_url="https://capa/obra.jpg")
    edicao = conexao.execute(
        text(
            "INSERT INTO edicao (obra_id, titulo, capa_url) "
            "VALUES (:o, 'Duna', 'https://capa/edicao.jpg') RETURNING id"
        ),
        {"o": obra},
    ).scalar_one()
    adicionar(conexao, LEITOR_ID, obra, 5, origem="busca", edicao_id=edicao)

    [item] = listar(conexao, LEITOR_ID)

    assert item.capa_url == "https://capa/edicao.jpg"
    assert item.titulo == "Dune"  # titulo_exibicao da Obra
    assert item.autores == ("Frank Herbert",)


# --- Eventos (SPEC §7.6) ---


def test_registrar_evento(conexao: Connection, duna: int) -> None:
    registrar_evento(conexao, LEITOR_ID, "busca_iniciada", texto="duna herbert")
    registrar_evento(conexao, LEITOR_ID, "sugestao_aberta", obra_id=duna, posicao=3)

    assert _eventos(conexao, "busca_iniciada") == [{"obra_id": None, "texto": "duna herbert"}]
    assert _eventos(conexao, "sugestao_aberta") == [{"obra_id": duna, "posicao": 3}]


def test_tipo_de_evento_desconhecido(conexao: Connection) -> None:
    with pytest.raises(ValueError, match="Tipo de evento"):
        registrar_evento(conexao, LEITOR_ID, "qualquer")


# --- Montagem da Estante (SPEC §7.4) ---


@pytest.fixture
def generos(conexao: Connection) -> dict[str, int]:
    return {s: criar_genero(conexao, s) for s in ("fantasia", "terror", "poesia")}


def _obra_do_genero(conexao: Connection, titulo: str, genero: int, pop: int, forca=1.0) -> int:
    obra = criar_obra(conexao, titulo, ("Autor " + titulo,), popularidade=pop)
    ligar_genero(conexao, obra, genero, forca)
    return obra


def test_grade_intercala_os_generos_por_popularidade_e_forca(
    conexao: Connection, generos: dict[str, int]
) -> None:
    f1 = _obra_do_genero(conexao, "F1", generos["fantasia"], 1000)
    f2 = _obra_do_genero(conexao, "F2", generos["fantasia"], 900)
    f3 = _obra_do_genero(conexao, "F3", generos["fantasia"], 5000, forca=0.1)  # 500
    t1 = _obra_do_genero(conexao, "T1", generos["terror"], 300)
    t2 = _obra_do_genero(conexao, "T2", generos["terror"], 200)
    _obra_do_genero(conexao, "P1", generos["poesia"], 10_000)  # Gênero não escolhido

    grade = grade_da_montagem(conexao, LEITOR_ID, ["fantasia", "terror"])

    assert [c.obra_id for c in grade] == [f1, t1, f2, t2, f3]
    assert grade[0].titulo == "F1" and grade[0].autores == ("Autor F1",)


def test_grade_sem_repetir_obra_de_dois_generos(
    conexao: Connection, generos: dict[str, int]
) -> None:
    ambas = _obra_do_genero(conexao, "Ambas", generos["fantasia"], 1000)
    ligar_genero(conexao, ambas, generos["terror"], 1.0)
    t = _obra_do_genero(conexao, "T", generos["terror"], 10)

    grade = grade_da_montagem(conexao, LEITOR_ID, ["fantasia", "terror"])

    assert [c.obra_id for c in grade] == [ambas, t]


def test_grade_tira_a_estante_e_as_que_o_leitor_nao_leu(
    conexao: Connection, generos: dict[str, int]
) -> None:
    obras = [_obra_do_genero(conexao, f"F{i}", generos["fantasia"], 100 - i) for i in range(5)]
    adicionar(conexao, LEITOR_ID, obras[0], 4, origem="montagem")

    grade = grade_da_montagem(conexao, LEITOR_ID, ["fantasia"], excluir={obras[1]}, limite=2)

    assert [c.obra_id for c in grade] == [obras[2], obras[3]]


def test_grade_so_traz_obras_da_base(conexao: Connection, generos: dict[str, int]) -> None:
    do_leitor = criar_obra(conexao, "Minha", ("Eu",), origem="leitor", popularidade=10**6)
    ligar_genero(conexao, do_leitor, generos["fantasia"])
    assert grade_da_montagem(conexao, LEITOR_ID, ["fantasia"]) == []


def test_montagem_aberta_ate_5_notas(conexao: Connection, generos: dict[str, int]) -> None:
    obras = [_obra_do_genero(conexao, f"F{i}", generos["fantasia"], 100 - i) for i in range(6)]
    adicionar(conexao, LEITOR_ID, obras[5], None, origem="busca")  # sem Nota não conta

    for i, obra in enumerate(obras[:5]):
        assert montagem_pendente(conexao, LEITOR_ID)
        assert contar_notas(conexao, LEITOR_ID) == i
        adicionar(conexao, LEITOR_ID, obra, 4, origem="montagem")

    assert contar_notas(conexao, LEITOR_ID) == 5
    assert not montagem_pendente(conexao, LEITOR_ID)


def test_pular_fecha_a_montagem(conexao: Connection) -> None:
    assert montagem_pendente(conexao, LEITOR_ID)
    pular_montagem(conexao, LEITOR_ID)
    assert not montagem_pendente(conexao, LEITOR_ID)


def test_grade_de_tecnologia_poe_a_base_depois_a_lista_curada_depois_as_edicoes(
    conexao: Connection,
) -> None:
    """As Obras técnicas da Open Library têm popularidade 0 (SPEC §7.4, §8.8)."""
    tecnologia = criar_genero(conexao, "tecnologia")
    base = _obra_do_genero(conexao, "Pragmatic", tecnologia, 10_000, forca=0.6)
    da_ol = {}
    for titulo, edicoes, curada in [
        ("Muitas", 40, False),
        ("Poucas", 3, False),
        ("Curada", 1, True),
    ]:
        da_ol[titulo] = criar_obra(conexao, titulo, origem="open_library")
        conexao.execute(
            text("UPDATE obra SET edicoes_ol = :e, curada = :c WHERE id = :o"),
            {"e": edicoes, "c": curada, "o": da_ol[titulo]},
        )
        ligar_genero(conexao, da_ol[titulo], tecnologia)
    leitor = criar_obra(conexao, "Do Leitor", origem="leitor")
    ligar_genero(conexao, leitor, tecnologia)

    grade = grade_da_montagem(conexao, LEITOR_ID, ["tecnologia"])

    assert [c.obra_id for c in grade] == [
        base,
        da_ol["Curada"],
        da_ol["Muitas"],
        da_ol["Poucas"],
    ]
