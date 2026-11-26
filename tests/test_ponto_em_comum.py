"""O Ponto em comum dos Parecidos (R5a, SPEC §8.3)."""

from fabricas import criar_genero, criar_obra, ligar_genero
from sqlalchemy import Connection, text

from recomendador.catalogo.generos import SLUG_TECNOLOGIA
from recomendador.config import LEITOR_ID
from recomendador.recomendacao import pagina_da_obra
from recomendador.recomendacao.ponto_em_comum import (
    MAX_TAGS,
    Metadados,
    PontoEmComum,
    ponto_em_comum,
    pontos_em_comum,
)

# --- a regra, sem banco ---


def test_autor_em_comum_vem_primeiro() -> None:
    obra = Metadados(("Robert T. Kiyosaki",), ("finance", "business"), ("Negócios",))
    vizinho = Metadados(("Robert T. Kiyosaki", "Sharon Lechter"), ("finance",), ("Negócios",))

    assert ponto_em_comum(obra, vizinho, {}) == PontoEmComum("autor", ("Robert T. Kiyosaki",))


def test_autor_compara_sem_acento_nem_caixa() -> None:
    obra = Metadados(("José Saramago",))
    assert ponto_em_comum(obra, Metadados(("JOSE SARAMAGO",)), {}).tipo == "autor"


def test_temas_sao_as_tags_em_comum_mais_raras_sem_as_genericas() -> None:
    obra = Metadados(("A",), ("non-fiction", "science", "anthropology", "evolution"))
    vizinho = Metadados(("B",), ("evolution", "non-fiction", "science", "anthropology"))
    obras_por_tag = {"non-fiction": 1883, "science": 900, "anthropology": 40, "evolution": 25}

    ponto = ponto_em_comum(obra, vizinho, obras_por_tag)

    assert ponto == PontoEmComum("temas", ("evolution", "anthropology"))


def test_tema_troca_o_hifen_por_espaco() -> None:
    obra = Metadados(("A",), ("decision-making",))
    ponto = ponto_em_comum(obra, Metadados(("B",), ("decision-making",)), {})
    assert ponto == PontoEmComum("temas", ("decision making",))


def test_so_tags_genericas_passam_para_o_genero() -> None:
    obra = Metadados(("A",), ("fiction", "adult"), ("Fantasia", "Clássicos"))
    vizinho = Metadados(("B",), ("fiction", "adult"), ("Clássicos", "Fantasia"))

    # O Gênero mais forte na Obra aberta.
    assert ponto_em_comum(obra, vizinho, {}) == PontoEmComum("genero", ("Fantasia",))


def test_tags_pessoais_que_escaparam_da_carga_nao_contam() -> None:
    pessoais = (
        "my-ebooks", "kindle-books", "book-club-books", "tbr", "own-to-read", "reread",
        "didn-t-finish", "paperback", "audiobooks", "ebooks",
    )  # fmt: skip
    obra = Metadados(("A",), (*pessoais, "mystery", "mythology"))
    vizinho = Metadados(("B",), (*pessoais, "mystery", "mythology"))

    ponto = ponto_em_comum(obra, vizinho, {"mystery": 2857, "mythology": 327})

    assert ponto == PontoEmComum("temas", ("mythology", "mystery"))  # "my" não é "my-"


def test_so_as_15_tags_de_maior_contagem_contam() -> None:
    tags = tuple(f"tag{i}" for i in range(MAX_TAGS)) + ("rara",)
    obra = Metadados(("A",), tags)
    vizinho = Metadados(("B",), ("rara",))
    assert ponto_em_comum(obra, vizinho, {"rara": 1}) is None


def test_sem_nada_em_comum_nao_ha_ponto() -> None:
    assert ponto_em_comum(Metadados(("A",), ("x",), ("G",)), Metadados(("B",), ("y",)), {}) is None


# --- no banco ---


def _tags(conexao: Connection, obra: int, tags: dict[str, int]) -> None:
    conexao.execute(
        text("INSERT INTO obra_tag (obra_id, tag, contagem) VALUES (:o, :t, :c)"),
        [{"o": obra, "t": t, "c": c} for t, c in tags.items()],
    )


def test_raridade_conta_as_obras_do_catalogo_com_a_tag(conexao: Connection) -> None:
    """ "space" está em 4 Obras e "dune" em 2: o tema mais raro vem primeiro. Assunto da
    Open Library (contagem 0) não conta como tag de leitores."""
    obra = criar_obra(conexao, "Dune", ("Frank Herbert",))
    vizinho = criar_obra(conexao, "Hyperion", ("Dan Simmons",))
    _tags(conexao, obra, {"space": 50, "dune": 10, "desert": 0})
    _tags(conexao, vizinho, {"space": 30, "dune": 5, "desert": 0})
    for i in range(2):
        _tags(conexao, criar_obra(conexao, f"Outra {i}", ("X",)), {"space": 1})

    pontos = pontos_em_comum(conexao, obra, [vizinho])

    assert pontos == {vizinho: PontoEmComum("temas", ("dune", "space"))}
    assert pontos_em_comum(conexao, obra, []) == {}


def test_pagina_da_obra_traz_o_ponto_em_comum_dos_parecidos(conexao: Connection) -> None:
    obra = criar_obra(conexao, "Animal Farm", ("George Orwell",))
    mesmo_autor = criar_obra(conexao, "1984", ("George Orwell",))
    mesmo_genero = criar_obra(conexao, "Brave New World", ("Aldous Huxley",))
    nada = criar_obra(conexao, "Emma", ("Jane Austen",))
    classicos = criar_genero(conexao, "classicos", "Clássicos")
    for o in (obra, mesmo_genero):
        ligar_genero(conexao, o, classicos)
    for tipo in ("conteudo", "coleitura"):
        execucao = conexao.execute(
            text(
                "INSERT INTO execucao_modelo (tipo, modelo, ativa) "
                f"VALUES ('{tipo}', 'teste', true) RETURNING id"
            )
        ).scalar_one()
        conexao.execute(
            text("INSERT INTO vizinho VALUES (:e, :o, :v, 0.5, :p)"),
            [
                {"e": execucao, "o": obra, "v": v, "p": p}
                for p, v in enumerate((mesmo_autor, mesmo_genero, nada), 1)
            ],
        )

    p = pagina_da_obra(conexao, obra, LEITOR_ID)

    assert p is not None
    assert [v.ponto_em_comum for v in p.parecidos] == [
        PontoEmComum("autor", ("George Orwell",)),
        PontoEmComum("genero", ("Clássicos",)),
        None,
    ]
    assert all(v.ponto_em_comum is None for v in p.quem_leu)  # só nos Parecidos


def test_tecnologia_nao_conta_como_genero_em_comum(conexao: Connection) -> None:
    """Os Parecidos de uma Obra técnica são todos de Tecnologia: "Também Tecnologia" não diz
    nada. Outro Gênero em comum continua valendo."""
    obra = criar_obra(conexao, "Designing Data-Intensive Applications", ("Martin Kleppmann",))
    so_tecnologia = criar_obra(conexao, "Database Internals", ("Alex Petrov",))
    tambem_negocios = criar_obra(conexao, "The Phoenix Project", ("Gene Kim",))
    tecnologia = criar_genero(conexao, SLUG_TECNOLOGIA, "Tecnologia")
    negocios = criar_genero(conexao, "negocios", "Negócios e autoajuda")
    for o in (obra, so_tecnologia, tambem_negocios):
        ligar_genero(conexao, o, tecnologia)
    for o in (obra, tambem_negocios):
        ligar_genero(conexao, o, negocios, forca=0.1)

    pontos = pontos_em_comum(conexao, obra, [so_tecnologia, tambem_negocios])

    assert pontos == {
        so_tecnologia: None,
        tambem_negocios: PontoEmComum("genero", ("Negócios e autoajuda",)),
    }
