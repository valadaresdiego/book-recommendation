"""Adicionar (R1 + R2, SPEC §11): busca → escolha → "É uma destas?" → Nota → salvar."""

import streamlit as st
from componentes import busca_e_adicionar

st.title("Adicionar")
st.caption("Busque no Catálogo e no Google Books por título, autor ou ISBN.")
busca_e_adicionar("adicionar")
