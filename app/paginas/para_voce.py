"""Para você (R4, SPEC §8.5 e §11): até 20 Sugestões em cards, cada uma com o Motivo.

Fase 4 (§8.6): filtros por Gênero e por Edição em português (R10), "Por quê?" com os
Contribuintes (R11), "Quero ler" (R8) e "Não tenho interesse" (R7). Fase 5 (§8.7):
"Comecei a ler" (R13).
"""

import streamlit as st
from componentes import (
    LEITOR,
    abrir_obra,
    autores_em_texto,
    comecei_a_ler,
    dispensar,
    ja_li,
    mostrar_capa,
    quero_ler,
    texto_do_contribuinte,
    texto_do_motivo,
)

from recomendador import catalogo, estante, recomendacao

COLUNAS = 4


@st.cache_data(ttl=30, show_spinner=False)
def _para_voce(generos: tuple[str, ...], so_edicao_pt: bool) -> recomendacao.ParaVoce:
    with recomendacao.transacao() as conn:
        return recomendacao.para_voce(conn, LEITOR, generos=generos, so_edicao_pt=so_edicao_pt)


@st.cache_data(ttl=3600, show_spinner=False)
def _generos() -> dict[str, str]:
    with catalogo.transacao() as conn:
        return {g.slug: g.nome for g in catalogo.listar_generos(conn)}


def _registrar_exibicao(r: recomendacao.ParaVoce, filtros: tuple) -> None:
    """`sugestao_exibida`, uma vez por item a cada abertura da lista (O2). Mudar um filtro
    conta como nova abertura (§8.6)."""
    rerun = st.session_state.get("pagina-anterior") == st.session_state.get("pagina-atual")
    if rerun and st.session_state.get("pv-filtros-exibidos") == filtros:
        return  # um rerun dentro da página, não uma abertura
    st.session_state["pv-filtros-exibidos"] = filtros
    with estante.transacao() as conn:
        for posicao, s in enumerate(r.sugestoes, 1):
            estante.registrar_evento(
                conn,
                LEITOR,
                "sugestao_exibida",
                s.obra_id,
                posicao=posicao,
                pontuacao=round(s.pontuacao, 4),
                motivo_obra_id=s.motivo_obra_id,
                execucoes=list(r.execucoes),
            )


st.title("Para você")

generos = _generos()
escolhidos = st.pills(
    "Gêneros",
    list(generos),
    format_func=generos.get,
    selection_mode="multi",
    key="pv-generos",
)
so_edicao_pt = st.toggle("Só com edição em português", key="pv-pt")
filtros = (tuple(sorted(escolhidos or ())), bool(so_edicao_pt))
r = _para_voce(*filtros)

if not r.suficiente:
    st.info(f"Avalie pelo menos {r.minimo} livros para receber sugestões.")
    st.progress(min(r.notas / r.minimo, 1.0), text=f"{r.notas} de {r.minimo}")
    st.page_link("paginas/montagem.py", label="Montagem da Estante", icon="🧩")
    st.stop()

if not r.sugestoes:
    if filtros != ((), False):
        st.info("Nenhuma sugestão passa nesses filtros. Tire algum para ver mais.")
    else:
        st.info(
            "Ainda não há sugestões: os livros com nota alta da sua Estante não têm parecidos "
            "calculados. Dê nota a mais livros."
        )
    st.stop()

_registrar_exibicao(r, filtros)
st.caption(f"{len(r.sugestoes)} sugestões a partir das suas {r.notas} notas.")

posicoes = st.session_state.setdefault("posicao-da-sugestao", {})
for inicio in range(0, len(r.sugestoes), COLUNAS):
    linha = enumerate(r.sugestoes[inicio : inicio + COLUNAS], inicio + 1)
    for coluna, (posicao, s) in zip(st.columns(COLUNAS), linha, strict=False):
        posicoes[s.obra_id] = posicao
        with coluna.container(border=True):
            mostrar_capa(s.capa_url, s.titulo_exibicao, s.autores, 110)
            if st.button(
                f"**{s.titulo_exibicao}**",
                key=f"pv-abrir-{s.obra_id}",
                type="tertiary",
                help="Abrir a página do livro",
            ):
                abrir_obra(s.obra_id, posicao)
            st.caption(autores_em_texto(s.autores[:2]))
            st.markdown(texto_do_motivo(s.motivo_nota, s.motivo_titulo))
            # Popover com `key`: o estado fica preso à Obra, não à posição do card.
            with st.popover("Por quê?", use_container_width=True, key=f"pv-{s.obra_id}-porque"):
                for c in s.contribuintes:
                    st.markdown(texto_do_contribuinte(c))
            quero_ler(s.obra_id, s.titulo_exibicao, f"pv-{s.obra_id}")
            comecei_a_ler(s.obra_id, s.titulo_exibicao, f"pv-{s.obra_id}")
            ja_li(s.obra_id, s.titulo_exibicao, f"pv-{s.obra_id}")
            dispensar(s.obra_id, s.titulo_exibicao, f"pv-{s.obra_id}")
