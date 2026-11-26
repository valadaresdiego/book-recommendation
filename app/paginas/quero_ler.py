"""Quero ler (R8, SPEC §8.6 e §11): as Obras guardadas para ler depois, fora da Estante.

A busca entra aqui também, só com o botão "Quero ler": aberta com a lista vazia, atrás de um
toggle quando não está.

O seletor "Geral" / "Tecnologia" separa as Obras técnicas (Gênero "Tecnologia"), como em
"Para você" (§8.8).
"""

import streamlit as st
from componentes import (
    LEITOR,
    abrir_obra,
    autores_em_texto,
    busca_e_adicionar,
    busca_tem_aviso,
    comecei_a_ler,
    ja_li,
    mostrar_capa,
    tirar_de_quero_ler,
)

from recomendador import estante

GERAL, TECNOLOGIA = "geral", "tecnologia"
ROTULOS = {GERAL: "Geral", TECNOLOGIA: "Tecnologia"}


def _livros(n: int) -> str:
    return "1 livro" if n == 1 else f"{n} livros"


@st.cache_data(ttl=30, show_spinner=False)
def _lista() -> list[estante.ItemQueroLer]:
    with estante.transacao() as conn:
        return estante.listar_quero_ler(conn, LEITOR)


st.title("Quero ler")
itens = _lista()

if not itens:
    st.info(
        "Sua lista Quero ler está vazia. Busque um livro que quer ler ou guarde as sugestões "
        "de Para você."
    )
    st.page_link("paginas/para_voce.py", label="Ver Para você", icon="✨")
    busca_e_adicionar("quero_ler", destino="quero_ler")
    st.stop()

st.caption(f"{_livros(len(itens))} na lista.")
if busca_tem_aviso("quero_ler"):
    st.session_state["ql-buscar"] = True  # a mensagem de "entrou na lista" aparece na busca
if st.toggle("Buscar livro", key="ql-buscar"):
    with st.container(border=True):
        busca_e_adicionar("quero_ler", destino="quero_ler")

por_lista = {
    GERAL: [i for i in itens if not i.tecnica],
    TECNOLOGIA: [i for i in itens if i.tecnica],
}
lista = (
    st.segmented_control(
        "Lista",
        list(ROTULOS),
        format_func=lambda c: f"{ROTULOS[c]} ({len(por_lista[c])})",
        default=GERAL,
        key="ql-lista",
        label_visibility="collapsed",
    )
    or GERAL  # desmarcar o botão escolhido volta para a lista geral
)
if not por_lista[lista]:
    st.info(
        "Nenhum livro técnico na lista."
        if lista == TECNOLOGIA
        else "Só há livros técnicos na lista."
    )

posicoes = st.session_state.setdefault("posicao-da-sugestao", {})
for item in por_lista[lista]:
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
