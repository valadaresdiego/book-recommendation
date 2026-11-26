"""Estante: Leituras, Notas, Montagem da Estante, Eventos (SPEC §7), Dispensa e Quero ler
(§8.6) e Estou lendo (§8.7).

O `app/` usa só o que está exportado aqui. Todas as funções recebem uma `Connection` e não
fazem commit: quem chama abre a transação (`transacao()`).
"""

from recomendador.config import LEITOR_ID
from recomendador.db.sessao import transacao
from recomendador.estante.eventos import TIPOS_DE_EVENTO, registrar_evento
from recomendador.estante.leituras import (
    ItemEstante,
    JaNaEstante,
    Leitura,
    adicionar,
    contar_notas,
    leitura_da_obra,
    listar,
    mudar_nota,
    remover,
)
from recomendador.estante.listas import (
    ItemEstouLendo,
    ItemQueroLer,
    JaEmQueroLer,
    desfazer_dispensa,
    dispensada,
    dispensar,
    listar_estou_lendo,
    listar_quero_ler,
    na_lista_estou_lendo,
    na_lista_quero_ler,
    quero_ler_da_obra,
    salvar_estou_lendo,
    salvar_quero_ler,
    tirar_de_estou_lendo,
    tirar_de_quero_ler,
)
from recomendador.estante.montagem import (
    NOTAS_PARA_SUGESTOES,
    OBRAS_POR_PAGINA,
    CardMontagem,
    grade_da_montagem,
    montagem_pendente,
    pular_montagem,
)

__all__ = [
    "LEITOR_ID",
    "NOTAS_PARA_SUGESTOES",
    "OBRAS_POR_PAGINA",
    "TIPOS_DE_EVENTO",
    "CardMontagem",
    "ItemEstante",
    "ItemEstouLendo",
    "ItemQueroLer",
    "JaEmQueroLer",
    "JaNaEstante",
    "Leitura",
    "adicionar",
    "contar_notas",
    "desfazer_dispensa",
    "dispensada",
    "dispensar",
    "grade_da_montagem",
    "leitura_da_obra",
    "listar",
    "listar_estou_lendo",
    "listar_quero_ler",
    "montagem_pendente",
    "mudar_nota",
    "na_lista_estou_lendo",
    "na_lista_quero_ler",
    "pular_montagem",
    "quero_ler_da_obra",
    "registrar_evento",
    "remover",
    "salvar_estou_lendo",
    "salvar_quero_ler",
    "tirar_de_estou_lendo",
    "tirar_de_quero_ler",
    "transacao",
]
