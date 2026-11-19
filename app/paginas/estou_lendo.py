"""Estou lendo (R13, SPEC §8.7 e §11): as Obras começadas, sem página nem percentual."""

import streamlit as st
from componentes import (
    LEITOR,
    abrir_obra,
    autores_em_texto,
    ja_li,
    mostrar_capa,
    parei_de_ler,
)

from recomendador import estante


@st.cache_data(ttl=30, show_spinner=False)
def _lista() -> list[estante.ItemEstouLendo]:
    with estante.transacao() as conn:
        return estante.listar_estou_lendo(conn, LEITOR)


st.title("Estou lendo")
itens = _lista()

if not itens:
    st.info("Você não está lendo nada agora. Escolha a próxima leitura na sua lista Quero ler.")
    st.page_link("paginas/quero_ler.py", label="Ver Quero ler", icon="🔖")
    st.stop()

st.caption("1 livro em leitura." if len(itens) == 1 else f"{len(itens)} livros em leitura.")

posicoes = st.session_state.setdefault("posicao-da-sugestao", {})
for item in itens:
    if item.posicao is not None:
        # Veio de "Para você": o "Já li" grava com origem 'sugestao' (O5, §8.7).
        posicoes.setdefault(item.obra_id, item.posicao)
    with st.container(border=True):
        capa, info, acoes = st.columns([1, 6, 2], vertical_alignment="center")
        with capa:
            mostrar_capa(item.capa_url, item.titulo, item.autores, 60)
        with info:
            if st.button(f"**{item.titulo}**", key=f"el-abrir-{item.obra_id}", type="tertiary"):
                abrir_obra(item.obra_id)
            st.caption(f"{autores_em_texto(item.autores)} · começou em {item.criado_em:%d/%m/%Y}")
        with acoes:
            ja_li(item.obra_id, item.titulo, f"el-{item.obra_id}")
            parei_de_ler(item.obra_id, item.titulo, f"el-{item.obra_id}")
