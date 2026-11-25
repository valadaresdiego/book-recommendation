"""`catalogo.texto.titulo_sem_ruido`: o que as livrarias põem no fim do título (SPEC §6.2)."""

import pytest

from recomendador.catalogo.texto import titulo_sem_ruido


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
