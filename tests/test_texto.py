"""`catalogo.texto`: ruído no fim do título (SPEC §6.2) e a chave do autor (§7.2, §8.8)."""

import pytest

from recomendador.catalogo.texto import chave_do_autor, sem_autores_repetidos, titulo_sem_ruido


@pytest.mark.parametrize(
    ("titulo", "limpo"),
    [
        # Idioma
        ("Torto arado (Em Portugues do Brasil)", "Torto arado"),
        ("Duna (Portuguese Edition)", "Duna"),
        # Prêmios
        ("Torto Arado (Prémio LeYa 2018)", "Torto Arado"),
        ("Torto Arado (Vencedor do Prêmio Jabuti 2020)", "Torto Arado"),
        ("Tudo é rio (Finalista do Premio São Paulo de Literatura)", "Tudo é rio"),
        ("The Road (Pulitzer Prize Winner)", "The Road"),
        ("Leviathan Wakes (Hugo Award Nominee)", "Leviathan Wakes"),
        # Selos de edição, tradução e preço
        ("Dom Casmurro (Edição Especial)", "Dom Casmurro"),
        ("O Pequeno Príncipe (Edição comemorativa)", "O Pequeno Príncipe"),
        ("Memórias Póstumas de Brás Cubas (Edição de Bolso)", "Memórias Póstumas de Brás Cubas"),
        ("Dama das Camélias (Romance) (Ilustrado)", "Dama das Camélias (Romance)"),
        ("O Homem de Terno Marrom (Tradução Atualizada)", "O Homem de Terno Marrom"),
        (
            "O Adversário Secreto (tradução de 2022) (leitura Fácil, Fonte 12pt)",
            "O Adversário Secreto",
        ),
        ("ERA UMA VEZ UM RAPAZ -(EURO 17.46)", "ERA UMA VEZ UM RAPAZ"),
        # Junto com o idioma
        ("Os Miseráveis (Edição de luxo) (Em Portugues do Brasil)", "Os Miseráveis"),
    ],
)
def test_tira_idioma_premio_e_selo_de_edicao(titulo: str, limpo: str) -> None:
    assert titulo_sem_ruido(titulo) == limpo


@pytest.mark.parametrize(
    "titulo",
    [
        "Tentada (House of Night #6)",
        "Agnes Grey (Coleção Duetos)",
        "Fundação (Colecao: Trilogia)",
        "Acima de qualquer suspeita (Presumed innocent)",
        "O mestre (Guia do especialista)",
        "Lolita (tradução de Sergio Flaksman)",
        "(Prêmio Nobel)",  # o parêntese é o título inteiro
    ],
)
def test_mantem_serie_colecao_e_o_que_e_do_titulo(titulo: str) -> None:
    assert titulo_sem_ruido(titulo) == titulo


@pytest.mark.parametrize(
    ("com_titulo", "sem_titulo"),
    [
        ("Dr. Yuxing Yan", "Yuxing Yan"),
        ("Dr. Edward Lavieri", "Edward Lavieri"),
        ("Dra. Ana Maria Silva", "Ana Silva"),
        ("Prof. Diwakar Vaish", "Diwakar Vaish"),
        ("Profa Maria Souza", "Maria Souza"),
        ("DR. M. O. Faruque Sarker", "M. Sarker"),
    ],
)
def test_titulo_honorifico_nao_e_o_primeiro_nome(com_titulo: str, sem_titulo: str) -> None:
    assert chave_do_autor(com_titulo) == chave_do_autor(sem_titulo)


def test_pseudonimo_com_titulo_fica_como_esta() -> None:
    """Sem o "Dr.", sobraria só o sobrenome: o Dr. Seuss não vira "Seuss"."""
    assert chave_do_autor("Dr. Seuss") == ("dr", "seuss")


def test_o_mesmo_autor_com_e_sem_titulo_aparece_uma_vez() -> None:
    assert sem_autores_repetidos(["Yuxing Yan", "Dr. Yuxing Yan"]) == ["Yuxing Yan"]
