"""Gêneros: sincronização com o YAML e `mapear-generos` (SPEC §6.3)."""

from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from recomendador.catalogo.generos import (
    ARQUIVO_GENEROS,
    SLUG_TECNOLOGIA,
    generos_das_categorias,
    ler_categorias,
    ler_generos,
    registrar_categorias,
    sincronizar_generos,
)
from recomendador.catalogo.tipos import ResultadoBusca
from recomendador.pipeline.generos import categorias_das_edicoes_do_leitor, mapear_generos


def _yaml(tmp_path: Path, conteudo: str) -> Path:
    caminho = tmp_path / "generos.yaml"
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


def _generos(conexao: Connection) -> dict[str, set[str]]:
    linhas = conexao.execute(
        text("SELECT g.slug, t.tag FROM genero g LEFT JOIN genero_tag t ON t.genero_id = g.id")
    ).all()
    resultado: dict[str, set[str]] = {}
    for slug, tag in linhas:
        resultado.setdefault(slug, set()).update({tag} if tag else set())
    return resultado


def test_yaml_do_projeto_tem_19_generos() -> None:
    generos = ler_generos()
    assert len(generos) == 19
    assert generos[-1].slug == SLUG_TECNOLOGIA
    assert all(g.tags for g in generos)


def test_sincronizar_reflete_o_yaml(conexao: Connection, tmp_path: Path) -> None:
    sincronizar_generos(conexao, ARQUIVO_GENEROS)
    sincronizar_generos(conexao, ARQUIVO_GENEROS)  # idempotente
    assert len(_generos(conexao)) == 19

    menor = _yaml(
        tmp_path,
        "- {slug: fantasia, nome: Fantasia, tags: [fantasy, Magic]}\n"
        "- {slug: terror, nome: Terror, tags: [horror]}\n",
    )
    sincronizar_generos(conexao, menor)

    assert _generos(conexao) == {"fantasia": {"fantasy", "magic"}, "terror": {"horror"}}


def test_slug_repetido_e_recusado(tmp_path: Path) -> None:
    caminho = _yaml(
        tmp_path,
        "- {slug: a, nome: A, tags: [x]}\n- {slug: a, nome: B, tags: [y]}\n",
    )
    with pytest.raises(ValueError, match="repetido"):
        ler_generos(caminho)


def _obra_com_tags(conexao: Connection, tags: dict[str, int], origem: str = "base") -> int:
    obra_id = conexao.execute(
        text(
            "INSERT INTO obra (titulo, titulo_exibicao, origem) VALUES ('x', 'x', :origem) "
            "RETURNING id"
        ),
        {"origem": origem},
    ).scalar_one()
    conexao.execute(
        text("INSERT INTO obra_tag VALUES (:o, :t, :c)"),
        [{"o": obra_id, "t": t, "c": c} for t, c in tags.items()],
    )
    return obra_id


def _forcas(conexao: Connection, obra_id: int) -> dict[str, float]:
    return dict(
        conexao.execute(
            text(
                "SELECT g.slug, og.forca FROM obra_genero og JOIN genero g ON g.id = og.genero_id "
                "WHERE og.obra_id = :o"
            ),
            {"o": obra_id},
        ).all()
    )


def test_forca_e_a_fatia_das_tags_do_genero(conexao: Connection, tmp_path: Path) -> None:
    sincronizar_generos(
        conexao,
        _yaml(
            tmp_path,
            "- {slug: fantasia, nome: Fantasia, tags: [fantasy, magic]}\n"
            "- {slug: terror, nome: Terror, tags: [horror]}\n"
            "- {slug: poesia, nome: Poesia, tags: [poetry]}\n",
        ),
    )
    # 1000 de contagem útil: fantasia 700 (70 %), terror 60 (6 %), poesia 40 (4 %, fica fora).
    # O assunto da Open Library (contagem 0) não conta, nem para o Gênero nem no total.
    obra_id = _obra_com_tags(
        conexao,
        {"fantasy": 500, "magic": 200, "horror": 60, "poetry": 40, "adventure": 200, "Poetry": 0},
    )

    resumo = mapear_generos(conexao)

    assert _forcas(conexao, obra_id) == pytest.approx({"fantasia": 0.7, "terror": 0.06})
    assert resumo.obras == resumo.obras_com_genero == 1
    assert resumo.por_genero == {"Fantasia": 1, "Terror": 1, "Poesia": 0}

    mapear_generos(conexao)  # idempotente
    assert _forcas(conexao, obra_id) == pytest.approx({"fantasia": 0.7, "terror": 0.06})


def test_obra_sem_tags_fica_sem_genero(conexao: Connection) -> None:
    sincronizar_generos(conexao)
    obra_id = _obra_com_tags(conexao, {"assunto da ol": 0})

    resumo = mapear_generos(conexao)

    assert _forcas(conexao, obra_id) == {}
    assert resumo.obras_com_genero == 0


def test_tecnologia_nao_fica_com_as_biografias(conexao: Connection) -> None:
    """*Ghost in the Wires*: as tags de programação não fazem da autobiografia uma Obra técnica."""
    sincronizar_generos(conexao)
    tecnica = _obra_com_tags(conexao, {"programming": 600, "software": 100, "fiction": 300})
    memorias = _obra_com_tags(conexao, {"computers": 100, "memoir": 400, "nonfiction": 500})

    mapear_generos(conexao)

    assert SLUG_TECNOLOGIA in _forcas(conexao, tecnica)
    assert set(_forcas(conexao, memorias)) == {"biografias"}


def test_mapear_mantem_a_tecnologia_das_obras_da_open_library(conexao: Connection) -> None:
    """As Obras técnicas dos dumps ganham o Gênero no `carregar-tecnicas`, com força 1; os
    assuntos delas têm contagem 0 e não refariam a linha (SPEC §6.3, §8.8)."""
    sincronizar_generos(conexao)
    da_ol = _obra_com_tags(conexao, {"computer programming": 0}, origem="open_library")
    do_leitor = _obra_com_tags(conexao, {"python (computer program language)": 0}, "leitor")
    for obra_id in (da_ol, do_leitor):
        conexao.execute(
            text(
                "INSERT INTO obra_genero (obra_id, genero_id, forca) "
                "SELECT :o, id, 1 FROM genero WHERE slug = :s"
            ),
            {"o": obra_id, "s": SLUG_TECNOLOGIA},
        )

    mapear_generos(conexao)

    assert _forcas(conexao, da_ol) == {SLUG_TECNOLOGIA: 1.0}
    assert _forcas(conexao, do_leitor) == {SLUG_TECNOLOGIA: 1.0}


# --- Gênero das Obras do Leitor pelas categorias do Google Books (SPEC §6.3) ---


@pytest.mark.parametrize(
    ("categorias", "esperado"),
    [
        (["Computers / Data Science / Data Warehousing"], {"tecnologia"}),
        (["Business & Economics / Time Management", "Self-Help / General"], {"negocios-autoajuda"}),
        (
            ["Business & Economics / Decision-Making", "Psychology / Cognitive Psychology"],
            {"negocios-autoajuda", "ciencia"},
        ),
        (["Fiction / Fantasy / Epic"], {"fantasia"}),  # o prefixo mais longo vence
        (["FICTION / science fiction / General"], {"ficcao-cientifica"}),
        (["Fiction"], set()),  # "Fiction" sozinho não diz o Gênero
        (["Technology & Engineering / Civil / General"], set()),  # engenharia não é Tecnologia
        # Steve Jobs: biografia sobre tecnologia não é técnica.
        (
            ["Biography & Autobiography / Science & Technology", "Computers / History"],
            {"biografias"},
        ),
        ([], set()),
    ],
)
def test_generos_das_categorias(categorias: list[str], esperado: set[str]) -> None:
    assert generos_das_categorias(categorias) == esperado


def test_mapa_de_categorias_so_aponta_para_generos_da_lista() -> None:
    slugs = {g.slug for g in ler_generos()}
    assert set(ler_categorias().values()) <= slugs


def test_categorias_dao_genero_so_a_obra_do_leitor(conexao: Connection) -> None:
    sincronizar_generos(conexao)
    do_leitor = _obra_com_tags(conexao, {"assunto da ol": 0}, origem="leitor")
    da_base = _obra_com_tags(conexao, {"fantasy": 100})

    registrar_categorias(conexao, do_leitor, ("Computers / Data Science / General",))
    registrar_categorias(conexao, da_base, ("Computers / Programming / General",))

    assert _forcas(conexao, do_leitor) == {SLUG_TECNOLOGIA: 1.0}
    assert SLUG_TECNOLOGIA not in _forcas(conexao, da_base)
    tags = conexao.execute(
        text("SELECT tag, contagem FROM obra_tag WHERE obra_id = :o ORDER BY tag"), {"o": do_leitor}
    ).all()
    assert [tuple(t) for t in tags] == [
        ("assunto da ol", 0),
        ("google:computers / data science / general", 0),
    ]
    # A Obra da Base fica só com as tags de leitores: nada do Google vai para ela.
    assert (
        conexao.execute(
            text("SELECT count(*) FROM obra_tag WHERE obra_id = :o AND tag LIKE 'google:%'"),
            {"o": da_base},
        ).scalar_one()
        == 0
    )


def test_mapear_refaz_o_genero_das_categorias(conexao: Connection) -> None:
    sincronizar_generos(conexao)
    obra = _obra_com_tags(conexao, {"assunto da ol": 0}, origem="leitor")
    registrar_categorias(
        conexao, obra, ("Business & Economics / Decision-Making", "Psychology / Cognitive")
    )

    mapear_generos(conexao)

    assert _forcas(conexao, obra) == {"negocios-autoajuda": 1.0, "ciencia": 1.0}


class _GoogleFalso:
    def __init__(self, categorias: dict[str, tuple[str, ...]]) -> None:
        self.categorias = categorias
        self.pedidos: list[str] = []

    def volume(self, volume_id: str) -> ResultadoBusca | None:
        self.pedidos.append(volume_id)
        return ResultadoBusca(
            titulo="x", autores=(), ano=None, capa_url=None, categorias=self.categorias[volume_id]
        )


def _edicao(conexao: Connection, obra_id: int, volume: str) -> None:
    conexao.execute(
        text("INSERT INTO edicao (obra_id, google_volume_id, titulo) VALUES (:o, :v, 'x')"),
        {"o": obra_id, "v": volume},
    )


def test_categorias_das_edicoes_do_leitor_ja_gravadas(conexao: Connection) -> None:
    """As Obras do Leitor de antes desta regra ganham o Gênero uma vez, pela Edição do
    Google Books que já têm; a que já tem categorias não pede de novo."""
    sincronizar_generos(conexao)
    sql = _obra_com_tags(conexao, {"x": 0}, origem="leitor")
    _edicao(conexao, sql, "yhp9EAAAQBAJ")
    ja_feita = _obra_com_tags(conexao, {"google:computers": 0}, origem="leitor")
    _edicao(conexao, ja_feita, "outro")
    da_base = _obra_com_tags(conexao, {"fantasy": 10})
    _edicao(conexao, da_base, "da-base")
    gb = _GoogleFalso({"yhp9EAAAQBAJ": ("Computers / Data Science / General",)})

    assert categorias_das_edicoes_do_leitor(conexao, gb) == 1

    assert gb.pedidos == ["yhp9EAAAQBAJ"]
    assert _forcas(conexao, sql) == {SLUG_TECNOLOGIA: 1.0}
