"""Quero ler (R8, SPEC §8.6 e §11): as Obras guardadas para ler depois, fora da Estante."""

import streamlit as st
from componentes import (
    LEITOR,
    abrir_obra,
    autores_em_texto,
    comecei_a_ler,
    ja_li,
    mostrar_capa,
    tirar_de_quero_ler,
)

from recomendador import estante


@st.cache_data(ttl=30, show_spinner=False)
def _lista() -> list[estante.ItemQueroLer]:
    with estante.transacao() as conn:
        return estante.listar_quero_ler(conn, LEITOR)


st.title("Quero ler")
itens = _lista()

if not itens:
    st.info("Sua lista Quero ler está vazia. Guarde aqui as sugestões que quer ler depois.")
    st.page_link("paginas/para_voce.py", label="Ver Para você", icon="✨")
    st.stop()

st.caption("1 livro na lista." if len(itens) == 1 else f"{len(itens)} livros na lista.")

posicoes = st.session_state.setdefault("posicao-da-sugestao", {})
for item in itens:
    if item.posicao is not None:
        # Veio de "Para você": o "Já li" grava com origem 'sugestao' (O5, §8.6).
        posicoes.setdefault(item.obra_id, item.posicao)
    with st.container(border=True):
        capa, info, acoes = st.columns([1, 6, 2], vertical_alignment="center")
        with capa:
            mostrar_capa(item.capa_url, item.titulo, item.autores, 60)
        with info:
            if st.button(f"**{item.titulo}**", key=f"ql-abrir-{item.obra_id}", type="tertiary"):
                abrir_obra(item.obra_id)
            st.caption(f"{autores_em_texto(item.autores)} · guardado em {item.criado_em:%d/%m/%Y}")
        with acoes:
            comecei_a_ler(item.obra_id, item.titulo, f"ql-{item.obra_id}")
            ja_li(item.obra_id, item.titulo, f"ql-{item.obra_id}")
            tirar_de_quero_ler(item.obra_id, item.titulo, f"ql-{item.obra_id}")
