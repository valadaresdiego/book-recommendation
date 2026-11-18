"""Montagem da Estante (R12, SPEC §7.4): Gêneros → grade de Obras populares → 5 Notas."""

import streamlit as st
from componentes import LEITOR, autores_em_texto, busca_e_adicionar, depois_de_gravar, mostrar_capa

from recomendador import catalogo, estante

COLUNAS = 6
META = estante.NOTAS_PARA_SUGESTOES


@st.cache_data(ttl=3600, show_spinner=False)
def _generos() -> list[catalogo.GeneroDoCatalogo]:
    with catalogo.transacao() as conn:
        return catalogo.listar_generos(conn)


def _contar_notas() -> int:
    with estante.transacao() as conn:
        return estante.contar_notas(conn, LEITOR)


def _carregar_mais(generos: list[str]) -> None:
    """Acrescenta a próxima página de cards, sem repetir os já mostrados nem os "Não li"."""
    cards = st.session_state["montagem-cards"]
    excluir = {c.obra_id for c in cards} | st.session_state["montagem-nao-li"]
    with estante.transacao() as conn:
        cards += estante.grade_da_montagem(conn, LEITOR, generos, excluir=excluir)


def _dar_nota(obra_id: int) -> None:
    valor = st.session_state[f"montagem-nota-{obra_id}"]
    nota = None if valor is None else valor + 1
    notas = st.session_state["montagem-notas"]
    with estante.transacao() as conn:
        if obra_id in notas:
            estante.mudar_nota(conn, LEITOR, obra_id, nota)
        else:
            try:
                estante.adicionar(conn, LEITOR, obra_id, nota, origem="montagem")
            except estante.JaNaEstante:
                estante.mudar_nota(conn, LEITOR, obra_id, nota)
    notas[obra_id] = nota
    depois_de_gravar()


def _nao_li(obra_id: int) -> None:
    st.session_state["montagem-nao-li"].add(obra_id)


def _pular() -> None:
    with estante.transacao() as conn:
        estante.pular_montagem(conn, LEITOR)
    depois_de_gravar()


st.session_state.setdefault("montagem-cards", [])
st.session_state.setdefault("montagem-nao-li", set())  # só nesta sessão (R12)
st.session_state.setdefault("montagem-notas", {})
st.session_state.setdefault("montagem-generos-carregados", None)

st.title("Montagem da Estante")
st.write(
    "Escolha os gêneros de que você gosta e dê nota aos livros que já leu. "
    f"Com {META} notas, dá para receber sugestões."
)

notas = _contar_notas()
contador, acoes = st.columns([3, 2], vertical_alignment="center")
contador.progress(min(notas, META) / META, text=f"**{min(notas, META)} de {META} Notas**")
with acoes:
    if notas >= META:
        if st.button("Ver minhas sugestões", type="primary", use_container_width=True):
            # Na fase 1, "Para você" ainda não existe: o botão leva à Estante (SPEC §7.4).
            st.switch_page("paginas/estante.py")
    elif st.button("Pular por enquanto", on_click=_pular, use_container_width=True):
        st.switch_page("paginas/estante.py")

generos = _generos()
nomes = {g.slug: g.nome for g in generos}
escolhidos = st.pills(
    "Gêneros de interesse",
    list(nomes),
    format_func=nomes.get,
    selection_mode="multi",
    key="montagem-generos",
)

if st.toggle("Não achou? Buscar livro", key="montagem-buscar"):
    with st.container(border=True):
        busca_e_adicionar("montagem")

if not escolhidos:
    st.info("Escolha pelo menos 1 gênero para ver os livros.")
    st.stop()

if st.session_state["montagem-generos-carregados"] != escolhidos:
    st.session_state["montagem-generos-carregados"] = list(escolhidos)
    st.session_state["montagem-cards"] = []
    _carregar_mais(escolhidos)

nao_li = st.session_state["montagem-nao-li"]
visiveis = [c for c in st.session_state["montagem-cards"] if c.obra_id not in nao_li]
if not visiveis:
    st.info("Não há mais livros desses gêneros fora da sua Estante. Escolha outros gêneros.")

for inicio in range(0, len(visiveis), COLUNAS):
    for coluna, card in zip(st.columns(COLUNAS), visiveis[inicio : inicio + COLUNAS], strict=False):
        with coluna.container(border=True):
            mostrar_capa(card.capa_url, card.titulo, card.autores, 120)
            st.markdown(f"**{card.titulo}**")
            st.caption(autores_em_texto(card.autores[:2]))
            nota_dada = st.session_state["montagem-notas"].get(card.obra_id)
            st.feedback(
                "stars",
                key=f"montagem-nota-{card.obra_id}",
                default=None if nota_dada is None else nota_dada - 1,
                on_change=_dar_nota,
                args=(card.obra_id,),
            )
            if card.obra_id not in st.session_state["montagem-notas"]:
                st.button(
                    "Não li",
                    key=f"montagem-nao-li-{card.obra_id}",
                    on_click=_nao_li,
                    args=(card.obra_id,),
                    use_container_width=True,
                )

if visiveis and st.button("Mostrar mais"):
    _carregar_mais(escolhidos)
    st.rerun()
