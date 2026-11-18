"""Peças da UI usadas por mais de uma página. Só chama o que `catalogo` e `estante` exportam."""

import time

import streamlit as st

from recomendador import catalogo, estante

LEITOR = estante.LEITOR_ID


def mostrar_capa(url: str | None, titulo: str, autores, largura: int = 90) -> None:
    """A capa da Obra ou da Edição; sem capa, a reserva com título e autor."""
    st.image(catalogo.capa(url, titulo, tuple(autores)), width=largura)


def autores_em_texto(autores) -> str:
    return ", ".join(autores) if autores else "Autor desconhecido"


def depois_de_gravar() -> None:
    """Qualquer escrita limpa o cache de leitura (SPEC §11), para a mudança aparecer na hora."""
    st.cache_data.clear()


@st.cache_data(ttl=3600, show_spinner=False)
def _buscar(texto: str) -> catalogo.Busca:
    # Cache só durante a sessão do app (TTL de 1 h), como pedem os termos do Google Books.
    with catalogo.transacao() as conn:
        return catalogo.buscar(conn, texto, catalogo.google_books())


# --- Busca → escolha → "É uma destas?" → Nota → salvar (R1 + R2) ---


class _Estado:
    """As chaves de `st.session_state` de um fluxo de busca, separadas por página."""

    def __init__(self, prefixo: str) -> None:
        self.p = prefixo

    def __getitem__(self, nome: str):
        return st.session_state.get(f"{self.p}-{nome}")

    def __setitem__(self, nome: str, valor) -> None:
        st.session_state[f"{self.p}-{nome}"] = valor

    def chave(self, nome: str) -> str:
        return f"{self.p}-{nome}"

    def recomecar(self) -> None:
        for nome in ("texto", "resolucao", "escolhido"):
            self[nome] = None
        st.session_state.pop(self.chave("nota"), None)
        st.session_state.pop(self.chave("original"), None)


def busca_e_adicionar(prefixo: str) -> None:
    """O fluxo do R1 inteiro. `prefixo` separa o estado de cada página que o usa."""
    estado = _Estado(prefixo)
    if aviso := st.session_state.pop(estado.chave("salvo"), None):
        st.success(aviso, icon="✅")

    with st.form(estado.chave("form"), border=False, clear_on_submit=False):
        campo, botao = st.columns([5, 1], vertical_alignment="bottom")
        texto = campo.text_input(
            "Título, autor ou ISBN", placeholder="ex.: duna herbert", key=estado.chave("campo")
        )
        buscar = botao.form_submit_button("Buscar", use_container_width=True, type="primary")
    if buscar and texto.strip():
        estado.recomecar()
        estado["texto"] = texto.strip()
        estado["inicio"] = time.monotonic()
        with estante.transacao() as conn:
            estante.registrar_evento(conn, LEITOR, "busca_iniciada", texto=texto.strip())

    if estado["resolucao"] is not None:
        _confirmar(estado)
        return
    if estado["texto"]:
        _resultados(estado)
    _cadastro_manual(estado, aberto=False)


def _resultados(estado: _Estado) -> None:
    with st.spinner("Buscando…"):
        busca = _buscar(estado["texto"])
    if busca.google_indisponivel:
        st.caption("O Google Books não respondeu a tempo: mostrando só o Catálogo.")
    if not busca.resultados:
        st.info(f"Nada encontrado para “{estado['texto']}”. Você pode cadastrar manualmente.")
        _cadastro_manual(estado, aberto=True, chave="vazio")
        return
    for i, r in enumerate(busca.resultados):
        with st.container(border=True):
            capa, info, acao = st.columns([1, 6, 2], vertical_alignment="center")
            with capa:
                mostrar_capa(r.capa_url, r.titulo, r.autores, 60)
            ano = f" · {r.ano}" if r.ano else ""
            info.markdown(f"**{r.titulo}**  \n{autores_em_texto(r.autores)}{ano}")
            detalhes = []
            if r.no_catalogo:
                detalhes.append("no catálogo")
            if r.titulo_obra:
                detalhes.append(f"Obra: {r.titulo_obra}")
            if r.editora:
                detalhes.append(r.editora)
            if detalhes:
                info.caption(" · ".join(detalhes))
            if acao.button("Escolher", key=estado.chave(f"escolher-{i}"), use_container_width=True):
                _resolver(estado, r)


def _resolver(estado: _Estado, resultado: catalogo.ResultadoBusca) -> None:
    with st.spinner("Identificando a Obra…"), catalogo.transacao() as conn:
        estado["resolucao"] = catalogo.resolver_obra(conn, resultado, catalogo.open_library())
    st.rerun()


def _cadastro_manual(estado: _Estado, aberto: bool, chave: str = "manual") -> None:
    with st.expander("Não achou? Cadastrar manualmente", expanded=aberto):
        with st.form(estado.chave(f"form-{chave}"), border=False):
            titulo = st.text_input("Título", key=estado.chave(f"{chave}-titulo"))
            autor = st.text_input("Autor", key=estado.chave(f"{chave}-autor"))
            if st.form_submit_button("Continuar") and titulo.strip():
                with catalogo.transacao() as conn:
                    estado["resolucao"] = catalogo.resolver_manual(conn, titulo, autor)
                st.rerun()


def _resumo_escolhido(r: catalogo.Resolucao) -> None:
    edicao = r.edicao
    if edicao is None and r.obra_nova is not None:
        titulo, autores, url = r.obra_nova.titulo, r.obra_nova.autores, None
    elif edicao is not None:
        titulo, autores, url = edicao.titulo, edicao.autores, edicao.capa_url
    else:
        return
    capa, info = st.columns([1, 8], vertical_alignment="center")
    with capa:
        mostrar_capa(url, titulo, autores, 70)
    info.markdown(f"**{titulo}**  \n{autores_em_texto(autores)}")


_COMO = {
    "catalogo": "direto",
    "isbn": "pelo ISBN",
    "ol_work": "pela Open Library",
    "titulo_original": "pelo título original e o autor",
}


def _confirmar(estado: _Estado) -> None:
    r: catalogo.Resolucao = estado["resolucao"]
    _resumo_escolhido(r)

    if r.encontrou:
        with estante.transacao() as conn:
            item = estante.leitura_da_obra(conn, LEITOR, r.obra_id)
        if item is not None:
            st.warning(str(estante.JaNaEstante(item)), icon="📚")
            if st.button("Nova busca", key=estado.chave("de-novo")):
                estado.recomecar()
                st.rerun()
            return

    escolha = None
    if r.obra_nova is not None:
        escolha = _e_uma_destas(estado, r)
    else:
        st.caption(f"Obra identificada no Catálogo {_COMO[r.confianca]}.")

    st.markdown("**Sua nota**")
    estrelas = st.feedback("stars", key=estado.chave("nota"))
    st.caption("Pode deixar sem nota: a Leitura fica na Estante, mas não entra nas sugestões.")

    salvar, cancelar = st.columns([1, 1])
    if cancelar.button("Cancelar", key=estado.chave("cancelar"), use_container_width=True):
        estado.recomecar()
        st.rerun()
    if salvar.button(
        "Salvar na Estante", key=estado.chave("salvar"), type="primary", use_container_width=True
    ):
        _salvar(estado, r, escolha, None if estrelas is None else estrelas + 1)


def _e_uma_destas(estado: _Estado, r: catalogo.Resolucao) -> int | None:
    """Regra 4: candidatas do Catálogo e o título original, se for tradução."""
    if r.candidatas:
        st.markdown("**É uma destas?**")
        opcoes = [None, *(c.obra_id for c in r.candidatas)]
        por_id = {c.obra_id: c for c in r.candidatas}

        def rotulo(obra_id: int | None) -> str:
            if obra_id is None:
                return "Nenhuma: é outra Obra"
            c = por_id[obra_id]
            ano = f" ({c.ano})" if c.ano else ""
            return f"{c.titulo}{ano} — {autores_em_texto(c.autores[:2])}"

        escolha = st.radio(
            "É uma destas?",
            opcoes,
            format_func=rotulo,
            key=estado.chave("candidata"),
            label_visibility="collapsed",
        )
        if escolha is not None:
            return escolha

    original, procurar = st.columns([5, 2], vertical_alignment="bottom")
    texto = original.text_input(
        "Título original (se for tradução)",
        value=r.obra_nova.titulo_original or "",
        key=estado.chave("original"),
    )
    if procurar.button("Procurar", key=estado.chave("procurar"), use_container_width=True):
        with catalogo.transacao() as conn:
            nova = catalogo.informar_titulo_original(conn, r, texto)
        estado["resolucao"] = nova
        if nova.encontrou:
            st.toast("Achei a Obra no Catálogo pelo título original.")
        st.rerun()
    return None


def _salvar(estado: _Estado, r: catalogo.Resolucao, escolha: int | None, nota: int | None) -> None:
    inicio = estado["inicio"]
    duracao = round(time.monotonic() - inicio, 1) if inicio else None
    original = st.session_state.get(estado.chave("original"))
    try:
        with catalogo.transacao() as conn:
            if escolha is None and original:
                r = catalogo.informar_titulo_original(conn, r, original)
            registrada = catalogo.registrar_resolucao(conn, r, escolha=escolha)
            estante.adicionar(
                conn,
                LEITOR,
                registrada.obra_id,
                nota,
                origem="manual" if r.edicao is None else "busca",
                edicao_id=registrada.edicao_id,
                duracao_s=duracao,
            )
            item = estante.leitura_da_obra(conn, LEITOR, registrada.obra_id)
    except estante.JaNaEstante as e:
        # A transação foi desfeita: nem a Edição nem a Obra nova ficam gravadas (R1).
        st.warning(str(e), icon="📚")
        return
    depois_de_gravar()
    estado.recomecar()
    estado["inicio"] = None
    nota_txt = f" com nota {nota}" if nota else " sem nota"
    st.session_state[estado.chave("salvo")] = f"{item.titulo} entrou na Estante{nota_txt}."
    st.rerun()
