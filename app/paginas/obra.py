"""Página da Obra (R5, SPEC §8.3), aberta por `?obra=<id>`: dados, Nota e Vizinhos."""

import streamlit as st
from componentes import LEITOR, abrir_obra, autores_em_texto, ja_li, mostrar_capa

from recomendador import recomendacao

COLUNAS = 5
SEM_COLEITURA = "Ainda não há dados de outros leitores para este livro"  # texto do PRD
SEM_PARECIDOS = "Os parecidos com este livro ainda não foram calculados."


@st.cache_data(ttl=30, show_spinner=False)
def _pagina(obra_id: int) -> recomendacao.PaginaObra | None:
    with recomendacao.transacao() as conn:
        return recomendacao.pagina_da_obra(conn, obra_id, LEITOR)


def _vizinhos(titulo: str, itens: list[recomendacao.ObraVizinha], vazio: str, chave: str):
    st.subheader(titulo)
    if not itens:
        st.caption(vazio)
        return
    for inicio in range(0, len(itens), COLUNAS):
        for coluna, v in zip(st.columns(COLUNAS), itens[inicio : inicio + COLUNAS], strict=False):
            with coluna.container(border=True):
                mostrar_capa(v.capa_url, v.titulo_exibicao, v.autores, 80)
                if st.button(v.titulo_exibicao, key=f"{chave}-{v.obra_id}", type="tertiary"):
                    abrir_obra(v.obra_id)
                lido = " · ✅ lido" if v.lido else ""
                st.caption(autores_em_texto(v.autores[:1]) + lido)


try:
    obra_id: int | None = int(st.query_params.get("obra", ""))
except ValueError:
    obra_id = None
p = _pagina(obra_id) if obra_id is not None else None
if p is None:
    st.warning("Livro não encontrado.")
    st.page_link("paginas/para_voce.py", label="Voltar para Para você", icon="✨")
    st.stop()

capa, info = st.columns([1, 4])
with capa:
    mostrar_capa(p.capa_url, p.titulo_exibicao, p.autores, 180)
with info:
    st.title(p.titulo_exibicao)
    if p.titulo_original:
        st.caption(f"Título original: {p.titulo_original}")
    ano = f" · {p.ano}" if p.ano else ""
    st.markdown(f"**{autores_em_texto(p.autores)}**{ano}")
    if p.generos:
        st.caption(" · ".join(p.generos))
    if p.na_estante:
        nota = f"sua nota: {'★' * p.nota}" if p.nota else "sem nota"
        st.success(f"Na sua Estante ({nota}).", icon="📚")
    else:
        ja_li(p.obra_id, p.titulo_exibicao, f"obra-{p.obra_id}")
    if p.descricao:
        st.write(p.descricao)

_vizinhos("Parecidos com este", p.parecidos, SEM_PARECIDOS, "parecido")
_vizinhos("Quem leu este também gostou", p.quem_leu, SEM_COLEITURA, "coleitura")
