"""Ponto de entrada do Streamlit (SPEC §11). A UI só chama o pacote `recomendador`."""

import streamlit as st

from recomendador import estante

st.set_page_config(page_title="Recomendador de Livros", page_icon="📚", layout="wide")

# A Montagem da Estante abre sozinha enquanto há menos de 5 Notas e o Leitor não pulou.
with estante.transacao() as conn:
    montagem_pendente = estante.montagem_pendente(conn, estante.LEITOR_ID)

paginas = [
    st.Page("paginas/para_voce.py", title="Para você", icon="✨", default=not montagem_pendente),
    st.Page("paginas/estante.py", title="Estante", icon="📚"),
    st.Page("paginas/adicionar.py", title="Adicionar", icon="➕"),
    st.Page(
        "paginas/montagem.py", title="Montagem da Estante", icon="🧩", default=montagem_pendente
    ),
    st.Page("paginas/obra.py", title="Obra", icon="📖"),
]

st.navigation(paginas).run()

st.caption(
    "Dados de leitores: goodbooks-10k (CC BY-SA 4.0). Metadados: Open Library e Google Books."
)
