"""Recomendação: embeddings, Coleitura, Vizinhos, "Para você" e Motivo (SPEC §8).

O `app/` usa só o que está exportado aqui. As funções recebem uma `Connection` e não fazem
commit: quem chama abre a transação (`transacao()`).
"""

from recomendador.db.sessao import transacao
from recomendador.recomendacao.embeddings import Codificador
from recomendador.recomendacao.interativo import (
    ModeloDiferente,
    calcular_vizinhos_da_obra,
    carregar_codificador,
    modelo_de_conteudo_ativo,
    pendente,
)
from recomendador.recomendacao.obra import (
    VIZINHOS_NA_PAGINA,
    ObraVizinha,
    PaginaObra,
    pagina_da_obra,
)
from recomendador.recomendacao.sugestoes import ParaVoce, Sugestao, para_voce

__all__ = [
    "VIZINHOS_NA_PAGINA",
    "Codificador",
    "ModeloDiferente",
    "ObraVizinha",
    "PaginaObra",
    "ParaVoce",
    "Sugestao",
    "calcular_vizinhos_da_obra",
    "carregar_codificador",
    "modelo_de_conteudo_ativo",
    "pagina_da_obra",
    "para_voce",
    "pendente",
    "transacao",
]
