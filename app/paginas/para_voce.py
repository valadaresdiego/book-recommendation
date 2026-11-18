"""Para você (R4, SPEC §8.5 e §11): até 20 Sugestões em cards, cada uma com o Motivo."""

import streamlit as st
from componentes import (
    LEITOR,
    abrir_obra,
    autores_em_texto,
    ja_li,
    mostrar_capa,
    texto_do_motivo,
)

from recomendador import estante, recomendacao

COLUNAS = 4


@st.cache_data(ttl=30, show_spinner=False)
def _para_voce() -> recomendacao.ParaVoce:
    with recomendacao.transacao() as conn:
        return recomendacao.para_voce(conn, LEITOR)


def _registrar_exibicao(r: recomendacao.ParaVoce) -> None:
    """`sugestao_exibida`, uma vez por item a cada abertura da lista (O2)."""
    if st.session_state.get("pagina-anterior") == st.session_state.get("pagina-atual"):
        return  # um rerun dentro da página, não uma abertura
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
r = _para_voce()

if not r.suficiente:
    st.info(f"Avalie pelo menos {r.minimo} livros para receber sugestões.")
    st.progress(min(r.notas / r.minimo, 1.0), text=f"{r.notas} de {r.minimo}")
    st.page_link("paginas/montagem.py", label="Montagem da Estante", icon="🧩")
    st.stop()

if not r.sugestoes:
    st.info(
        "Ainda não há sugestões: os livros com nota alta da sua Estante não têm parecidos "
        "calculados. Dê nota a mais livros."
    )
    st.stop()

_registrar_exibicao(r)
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
            ja_li(s.obra_id, s.titulo_exibicao, f"pv-{s.obra_id}")
