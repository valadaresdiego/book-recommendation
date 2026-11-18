"""Estante (R3, SPEC §7.5): Leituras com capa, título, autor e Nota editável."""

import streamlit as st
from componentes import LEITOR, autores_em_texto, depois_de_gravar, mostrar_capa

from recomendador import estante

ORDENS = {"data": "Data de inclusão", "nota": "Nota"}


@st.cache_data(ttl=30, show_spinner=False)
def _listar(ordem: str) -> list[estante.ItemEstante]:
    with estante.transacao() as conn:
        return estante.listar(conn, LEITOR, ordem=ordem)


def _mudar_nota(obra_id: int) -> None:
    valor = st.session_state[f"nota-{obra_id}"]
    with estante.transacao() as conn:
        estante.mudar_nota(conn, LEITOR, obra_id, None if valor is None else valor + 1)
    depois_de_gravar()


def _remover(obra_id: int, titulo: str) -> None:
    with estante.transacao() as conn:
        estante.remover(conn, LEITOR, obra_id)
    st.session_state.pop(f"nota-{obra_id}", None)
    depois_de_gravar()
    st.toast(f"{titulo} saiu da Estante.")


st.title("Estante")

ordem = st.segmented_control(
    "Ordenar por", list(ORDENS), format_func=ORDENS.get, default="data", key="estante-ordem"
)
itens = _listar(ordem or "data")

if not itens:
    st.info(
        "Sua Estante está vazia. Comece pela Montagem da Estante ou adicione um livro que já leu."
    )
    montagem, adicionar = st.columns(2)
    montagem.page_link("paginas/montagem.py", label="Montar minha Estante", icon="🧩")
    adicionar.page_link("paginas/adicionar.py", label="Adicionar um livro", icon="➕")
    st.stop()

com_nota = sum(1 for i in itens if i.nota)
st.caption(f"{len(itens)} Leituras, {com_nota} com nota.")

for item in itens:
    with st.container(border=True):
        capa, info, nota, acao = st.columns([1, 6, 3, 1], vertical_alignment="center")
        with capa:
            mostrar_capa(item.capa_url, item.titulo, item.autores, 60)
        info.markdown(f"**{item.titulo}**  \n{autores_em_texto(item.autores)}")
        info.caption(f"Incluída em {item.criado_em:%d/%m/%Y}")
        with nota:
            st.feedback(
                "stars",
                key=f"nota-{item.obra_id}",
                default=None if item.nota is None else item.nota - 1,
                on_change=_mudar_nota,
                args=(item.obra_id,),
            )
            if item.nota is None:
                st.caption("Sem nota")
        # A `key` prende o popover à Obra: sem ela, depois de remover um item, o popover
        # aberto passaria para o item seguinte, que ocupa a mesma posição.
        with acao.popover("🗑️", help="Remover da Estante", key=f"remover-pop-{item.obra_id}"):
            st.write(f"Tirar **{item.titulo}** da Estante?")
            st.button(
                "Remover",
                key=f"remover-{item.obra_id}",
                type="primary",
                on_click=_remover,
                args=(item.obra_id, item.titulo),
            )
