"""Gêneros: sincronização com o YAML e `mapear-generos` (SPEC §6.3)."""

from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from recomendador.catalogo.generos import (
    ARQUIVO_GENEROS,
    SLUG_TECNOLOGIA,
    ler_generos,
    sincronizar_generos,
)
from recomendador.pipeline.generos import mapear_generos


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
