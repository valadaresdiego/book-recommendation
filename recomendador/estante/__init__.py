"""Estante: Leituras, Notas, Montagem da Estante e Eventos (SPEC §7).

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
    "JaNaEstante",
    "Leitura",
    "adicionar",
    "contar_notas",
    "grade_da_montagem",
    "leitura_da_obra",
    "listar",
    "montagem_pendente",
    "mudar_nota",
    "pular_montagem",
    "registrar_evento",
    "remover",
    "transacao",
]
