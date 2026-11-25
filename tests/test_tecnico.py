"""`calcular-tecnico` e o lugar das Obras técnicas nos Vizinhos (SPEC §8.2, §8.8, ADR 0009)."""

import pytest
from codificador_falso import CodificadorDePalavras
from fabricas import criar_obra
from sqlalchemy import Connection, text

from recomendador.catalogo.generos import SLUG_TECNOLOGIA, sincronizar_generos
from recomendador.pipeline.conteudo import calcular_conteudo
from recomendador.pipeline.execucoes import ativar
from recomendador.pipeline.tecnico import calcular_tecnico


def _obra(conexao: Connection, titulo: str, autor: str, descricao: str, **kw) -> int:
    o = criar_obra(conexao, titulo, (autor,), **kw)
    conexao.execute(text("UPDATE obra SET descricao = :d WHERE id = :o"), {"d": descricao, "o": o})
    return o


def _tecnica(conexao: Connection, obra_id: int) -> None:
    conexao.execute(
        text(
            "INSERT INTO obra_genero (obra_id, genero_id, forca) "
            "SELECT :o, id, 1 FROM genero WHERE slug = :s"
        ),
        {"o": obra_id, "s": SLUG_TECNOLOGIA},
    )


@pytest.fixture
def catalogo(conexao: Connection) -> dict[str, int]:
    """Ficção e negócios da Base, uma Obra técnica da Base e três da Open Library."""
    sincronizar_generos(conexao)
    ids = {
        "duna": _obra(conexao, "Dune", "Frank Herbert", "desert planet spice empire"),
        "fundacao": _obra(conexao, "Foundation", "Isaac Asimov", "galactic empire history"),
        "rapido": _obra(
            conexao, "Thinking Fast and Slow", "Daniel Kahneman", "data statistics data statistics"
        ),
        "pragmatico": _obra(
            conexao, "The Pragmatic Programmer", "Andy Hunt", "software code craft programmer"
        ),
        "clean": _obra(
            conexao,
            "Clean Code",
            "Robert Martin",
            "software code craft functions",
            origem="open_library",
        ),
        "python": _obra(
            conexao,
            "Python for Data Analysis",
            "Wes McKinney",
            "python data statistics pandas",
            origem="open_library",
        ),
        "ml": _obra(
            conexao,
            "Designing Machine Learning Systems",
            "Chip Huyen",
            "machine learning data statistics production",
            origem="open_library",
        ),
    }
    for chave in ("pragmatico", "clean", "python", "ml"):
        _tecnica(conexao, ids[chave])
    return ids


@pytest.fixture
def conteudo(conexao: Connection, catalogo: dict[str, int], tmp_path) -> int:
    """A execução de conteúdo ativada: o `ativar` já refaz os Vizinhos técnicos."""
    execucao = calcular_conteudo(conexao, CodificadorDePalavras(), tmp_path, k=3).execucao_id
    ativar(conexao, execucao, tmp_path, forcar=True)
    return execucao


def _vizinhos(conexao: Connection, tipo: str) -> dict[int, list[int]]:
    saida: dict[int, list[int]] = {}
    for obra, vizinho in conexao.execute(
        text(
            "SELECT v.obra_id, v.vizinho_id FROM vizinho v "
            "JOIN execucao_modelo e ON e.id = v.execucao_id AND e.ativa "
            "WHERE e.tipo = CAST(:t AS tipo_execucao) ORDER BY v.obra_id, v.posicao"
        ),
        {"t": tipo},
    ):
        saida.setdefault(obra, []).append(vizinho)
    return saida


def test_obra_da_open_library_nunca_e_vizinho_de_conteudo(
    conexao: Connection, catalogo: dict[str, int], conteudo: int
) -> None:
    da_ol = {catalogo[c] for c in ("clean", "python", "ml")}
    vizinhos = _vizinhos(conexao, "conteudo")
    assert set(vizinhos) == set(catalogo.values())  # todas têm Vizinhos de conteúdo...
    assert not da_ol & {v for lista in vizinhos.values() for v in lista}  # ...mas não são um


def test_ativar_conteudo_cria_a_execucao_tecnica_ativa(
    conexao: Connection, catalogo: dict[str, int], conteudo: int
) -> None:
    tecnicas = {catalogo[c] for c in ("pragmatico", "clean", "python", "ml")}
    vizinhos = _vizinhos(conexao, "tecnico")

    assert set(vizinhos) == set(catalogo.values())  # toda Obra tem Vizinhos técnicos
    for obra, lista in vizinhos.items():
        assert set(lista) <= tecnicas - {obra}
    # A Obra de estatística da Base acha as técnicas de dados primeiro.
    assert set(vizinhos[catalogo["rapido"]][:2]) == {catalogo["python"], catalogo["ml"]}
    execucao = conexao.execute(
        text("SELECT modelo, parametros FROM execucao_modelo WHERE ativa AND tipo = 'tecnico'")
    ).one()
    assert execucao.modelo == "falso/palavras"
    assert execucao.parametros["conteudo_execucao_id"] == conteudo
    assert execucao.parametros["escala"] > 0


def test_obra_tecnica_nova_espera_o_codificador(
    conexao: Connection, catalogo: dict[str, int], conteudo: int
) -> None:
    nova = _obra(
        conexao, "Fluent Python", "Luciano Ramalho", "python idioms", origem="open_library"
    )
    _tecnica(conexao, nova)

    sem_modelo = calcular_tecnico(conexao, k=3)
    assert (sem_modelo.sem_embedding, sem_modelo.embeddings_novos) == (1, 0)
    assert nova not in _vizinhos(conexao, "tecnico")

    com_modelo = calcular_tecnico(conexao, CodificadorDePalavras(), k=3)
    assert (com_modelo.sem_embedding, com_modelo.embeddings_novos) == (0, 1)
    assert catalogo["python"] in _vizinhos(conexao, "tecnico")[nova]
    assert (
        conexao.execute(
            text("SELECT count(*) FROM execucao_modelo WHERE ativa AND tipo = 'tecnico'")
        ).scalar_one()
        == 1
    )


def test_obra_tecnica_do_leitor_continua_pendente_para_o_app(
    conexao: Connection, catalogo: dict[str, int], conteudo: int
) -> None:
    """§8.8: o `calcular-tecnico` só gera embedding das Obras `open_library`. A do Leitor
    fica pendente, para o app ou o `atualizar` gerar também os Vizinhos de conteúdo dela."""
    from recomendador.recomendacao import pendente

    do_leitor = _obra(conexao, "Ruido", "Daniel Kahneman", "data statistics", origem="leitor")
    _tecnica(conexao, do_leitor)

    r = calcular_tecnico(conexao, CodificadorDePalavras(), k=3)

    assert (r.embeddings_novos, r.sem_embedding) == (0, 1)
    assert pendente(conexao, do_leitor)


def test_sem_obras_tecnicas_nao_cria_execucao(conexao: Connection, tmp_path) -> None:
    sincronizar_generos(conexao)
    _obra(conexao, "Dune", "Frank Herbert", "desert")
    _obra(conexao, "Emma", "Jane Austen", "village")
    execucao = calcular_conteudo(conexao, CodificadorDePalavras(), tmp_path, k=1).execucao_id
    ativar(conexao, execucao, tmp_path, forcar=True)

    assert calcular_tecnico(conexao).execucao_id is None
    assert _vizinhos(conexao, "tecnico") == {}


def test_obra_do_leitor_ganha_vizinhos_tecnicos_na_hora(
    conexao: Connection, catalogo: dict[str, int], conteudo: int
) -> None:
    """§7.3: além dos Vizinhos de conteúdo (só da Base), os técnicos, para ela poder ser
    Motivo na aba "Tecnologia"."""
    from recomendador.recomendacao.interativo import calcular_vizinhos_da_obra

    do_leitor = _obra(conexao, "Ruido", "Daniel Kahneman", "data statistics", origem="leitor")

    calcular_vizinhos_da_obra(conexao, do_leitor, CodificadorDePalavras(), k=2)

    tecnicas = {catalogo[c] for c in ("pragmatico", "clean", "python", "ml")}
    assert set(_vizinhos(conexao, "tecnico")[do_leitor]) <= tecnicas
    assert len(_vizinhos(conexao, "tecnico")[do_leitor]) == 2
    da_ol = {catalogo[c] for c in ("clean", "python", "ml")}
    assert not da_ol & set(_vizinhos(conexao, "conteudo")[do_leitor])


# --- "Para você": aba "Tecnologia" e lista geral; página da Obra ---


def _notas(conexao: Connection, notas: dict[int, int]) -> None:
    from recomendador.config import LEITOR_ID

    conexao.execute(
        text(
            "INSERT INTO leitura (leitor_id, obra_id, nota, origem) VALUES (:l, :o, :n, 'manual')"
        ),
        [{"l": LEITOR_ID, "o": o, "n": n} for o, n in notas.items()],
    )


def test_aba_tecnologia_sugere_so_obras_tecnicas(
    conexao: Connection, catalogo: dict[str, int], conteudo: int
) -> None:
    """Com 3 Notas, nenhuma técnica, a aba já traz Sugestões, com Motivo não técnico (R14)."""
    from recomendador.config import LEITOR_ID
    from recomendador.recomendacao import para_voce, para_voce_tecnologia

    _notas(conexao, {catalogo["duna"]: 5, catalogo["fundacao"]: 4, catalogo["rapido"]: 5})
    tecnicas = {catalogo[c] for c in ("pragmatico", "clean", "python", "ml")}

    r = para_voce_tecnologia(conexao, LEITOR_ID)

    assert r.suficiente and r.sugestoes
    assert {s.obra_id for s in r.sugestoes} <= tecnicas
    dados = next(s for s in r.sugestoes if s.obra_id == catalogo["python"])
    assert dados.motivo_obra_id == catalogo["rapido"]
    tecnico = conexao.execute(
        text("SELECT id FROM execucao_modelo WHERE ativa AND tipo = 'tecnico'")
    ).scalar_one()
    assert r.execucoes == (tecnico,)
    assert tecnico not in para_voce(conexao, LEITOR_ID).execucoes


def test_lista_geral_nunca_traz_obra_da_open_library(
    conexao: Connection, catalogo: dict[str, int], conteudo: int
) -> None:
    from recomendador.config import LEITOR_ID
    from recomendador.recomendacao import para_voce

    _notas(conexao, {catalogo["duna"]: 5, catalogo["fundacao"]: 4, catalogo["pragmatico"]: 5})
    # Mesmo um Vizinho de conteúdo antigo (de antes da fase 6) não a traz de volta.
    conexao.execute(
        text("INSERT INTO vizinho VALUES (:e, :o, :v, 0.99, 99)"),
        {"e": conteudo, "o": catalogo["pragmatico"], "v": catalogo["clean"]},
    )

    sugeridas = {s.obra_id for s in para_voce(conexao, LEITOR_ID).sugestoes}

    assert not sugeridas & {catalogo[c] for c in ("clean", "python", "ml")}


def test_filtro_de_portugues_na_aba_tecnologia(
    conexao: Connection, catalogo: dict[str, int], conteudo: int
) -> None:
    from recomendador.config import LEITOR_ID
    from recomendador.recomendacao import para_voce_tecnologia

    _notas(conexao, {catalogo["duna"]: 5, catalogo["fundacao"]: 4, catalogo["rapido"]: 5})
    conexao.execute(
        text("UPDATE obra SET tem_edicao_pt = true WHERE id = :o"), {"o": catalogo["ml"]}
    )

    r = para_voce_tecnologia(conexao, LEITOR_ID, so_edicao_pt=True)

    assert [s.obra_id for s in r.sugestoes] == [catalogo["ml"]]


def test_parecidos_de_uma_obra_tecnica_sao_tecnicos(
    conexao: Connection, catalogo: dict[str, int], conteudo: int
) -> None:
    from recomendador.config import LEITOR_ID
    from recomendador.recomendacao import pagina_da_obra

    tecnicas = {catalogo[c] for c in ("pragmatico", "clean", "python", "ml")}
    clean = pagina_da_obra(conexao, catalogo["clean"], LEITOR_ID)
    duna = pagina_da_obra(conexao, catalogo["duna"], LEITOR_ID)

    assert clean is not None and duna is not None
    assert {v.obra_id for v in clean.parecidos} == tecnicas - {catalogo["clean"]}
    assert not {v.obra_id for v in duna.parecidos} & (tecnicas - {catalogo["pragmatico"]})
    assert clean.quem_leu == []
