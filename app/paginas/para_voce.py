"""Para você (R4): chega na fase 2. Na fase 1, só aponta para a Estante e a Montagem."""

import streamlit as st

st.title("Para você")
st.info("As sugestões ficam disponíveis na fase 2. Por enquanto, monte sua Estante.")
estante, montagem = st.columns(2)
estante.page_link("paginas/estante.py", label="Ver minha Estante", icon="📚")
montagem.page_link("paginas/montagem.py", label="Montagem da Estante", icon="🧩")
