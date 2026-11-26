"""Peças da UI usadas por mais de uma página. Só chama o que `catalogo` e `estante` exportam."""

import time
from collections.abc import Callable
from typing import Literal

import streamlit as st
from sqlalchemy import Connection

from recomendador import catalogo, estante, recomendacao

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


# --- Busca → escolha → "É uma destas?" → Nota → salvar (R1 + R2), ou Quero ler (R8) ---

# `os_dois`: Estante (com Nota) ou Quero ler; `quero_ler`: só Quero ler, sem estrelas.
Destino = Literal["os_dois", "quero_ler"]


class _Estado:
    """As chaves de `st.session_state` de um fluxo de busca, separadas por página."""

    def __init__(self, prefixo: str, destino: Destino = "os_dois") -> None:
        self.p = prefixo
        self.destino = destino

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


def busca_tem_aviso(prefixo: str) -> bool:
    """Se a busca acabou de salvar e tem a mensagem para mostrar (a página deixa a busca aberta)."""
    return _Estado(prefixo).chave("salvo") in st.session_state


def busca_e_adicionar(prefixo: str, destino: Destino = "os_dois") -> None:
    """O fluxo do R1 inteiro, que termina na Estante ou em Quero ler (R8) conforme o
    `destino`. `prefixo` separa o estado de cada página que o usa."""
    estado = _Estado(prefixo, destino)
    if aviso := st.session_state.pop(estado.chave("salvo"), None):
        st.success(aviso, icon="✅")

    with st.form(estado.chave("form"), border=False, clear_on_submit=False):
        campo, botao = st.columns([5, 1], vertical_alignment="bottom")
        texto = campo.text_input(
            "Título, autor ou ISBN",
            placeholder="ex.: duna herbert",
            help='Para buscar por editora: editora:packt django, ou editora:"alta books" python',
            key=estado.chave("campo"),
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

    so_quero_ler = estado.destino == "quero_ler"
    na_lista = None
    if r.encontrou:
        with estante.transacao() as conn:
            item = estante.leitura_da_obra(conn, LEITOR, r.obra_id)
            na_lista = estante.quero_ler_da_obra(conn, LEITOR, r.obra_id)
        recusa = None
        if item is not None:
            recusa = estante.JaNaEstante(item)
        elif na_lista is not None and so_quero_ler:
            recusa = estante.JaEmQueroLer(na_lista)
        if recusa is not None:
            st.warning(str(recusa), icon="📚")
            if st.button("Nova busca", key=estado.chave("de-novo")):
                estado.recomecar()
                st.rerun()
            return
        if na_lista is not None:
            # Já guardada: ainda dá para marcar como lida, mas não guardar de novo.
            st.info(f"{na_lista.titulo} já está na sua lista Quero ler.", icon="🔖")

    escolha = None
    if r.obra_nova is not None:
        escolha = _e_uma_destas(estado, r)
    else:
        st.caption(f"Obra identificada no Catálogo {_COMO[r.confianca]}.")

    estrelas = None
    if not so_quero_ler:
        st.markdown("**Sua nota**")
        estrelas = st.feedback("stars", key=estado.chave("nota"))
        st.caption(
            "Pode deixar sem nota: a Leitura fica na Estante, mas não entra nas sugestões. "
            "Ainda não leu? Guarde em Quero ler."
        )

    botoes = ([] if so_quero_ler else ["salvar"]) + ([] if na_lista else ["quero"])
    colunas = dict(zip([*botoes, "cancelar"], st.columns(len(botoes) + 1), strict=True))
    if colunas["cancelar"].button(
        "Cancelar", key=estado.chave("cancelar"), use_container_width=True
    ):
        estado.recomecar()
        st.rerun()
    if "quero" in colunas and colunas["quero"].button(
        "Quero ler",
        key=estado.chave("quero"),
        icon="🔖",
        type="primary" if so_quero_ler else "secondary",
        use_container_width=True,
    ):
        _guardar_em_quero_ler(estado, r, escolha)
    if "salvar" in colunas and colunas["salvar"].button(
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


def _gravar(
    estado: _Estado,
    r: catalogo.Resolucao,
    escolha: int | None,
    guardar: Callable[[Connection, catalogo.ObraRegistrada], str],
) -> None:
    """Grava a resolução e o destino numa transação só; `guardar` devolve a mensagem.

    Se o destino recusa (`JaNaEstante`, `JaEmQueroLer`), a transação é desfeita: nem a
    Edição nem a Obra nova ficam gravadas (R1). Depois, os Parecidos da Obra do Leitor.
    """
    original = st.session_state.get(estado.chave("original"))
    try:
        with catalogo.transacao() as conn:
            if escolha is None and original:
                r = catalogo.informar_titulo_original(conn, r, original)
            registrada = catalogo.registrar_resolucao(conn, r, escolha=escolha)
            aviso = guardar(conn, registrada)
    except (estante.JaNaEstante, estante.JaEmQueroLer) as e:
        st.warning(str(_recusa_relida(e)), icon="📚")
        return
    depois_de_gravar()
    calcular_parecidos(registrada.obra_id)
    estado.recomecar()
    estado["inicio"] = None
    st.session_state[estado.chave("salvo")] = aviso
    st.rerun()


def _recusa_relida(
    e: estante.JaNaEstante | estante.JaEmQueroLer,
) -> estante.JaNaEstante | estante.JaEmQueroLer:
    """A recusa com a Obra relida depois de desfeita a transação.

    Dentro dela, `registrar_resolucao` pode ter dado à candidata o título da Edição em
    português (§7.2), e o aviso sairia com o título da Edição recusada.
    """
    with estante.transacao() as conn:
        if isinstance(e, estante.JaNaEstante):
            item = estante.leitura_da_obra(conn, LEITOR, e.item.obra_id)
            return estante.JaNaEstante(item) if item else e
        item = estante.quero_ler_da_obra(conn, LEITOR, e.item.obra_id)
        return estante.JaEmQueroLer(item) if item else e


def _salvar(estado: _Estado, r: catalogo.Resolucao, escolha: int | None, nota: int | None) -> None:
    inicio = estado["inicio"]
    duracao = round(time.monotonic() - inicio, 1) if inicio else None

    def na_estante(conn, registrada: catalogo.ObraRegistrada) -> str:
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
        nota_txt = f" com nota {nota}" if nota else " sem nota"
        return f"{item.titulo} entrou na Estante{nota_txt}."

    _gravar(estado, r, escolha, na_estante)


def _guardar_em_quero_ler(estado: _Estado, r: catalogo.Resolucao, escolha: int | None) -> None:
    """Um livro buscado vai para Quero ler sem Nota e sem posição (fora do O2), com a
    Edição escolhida, que o "Já li" leva para a Leitura (ADR 0010)."""

    def em_quero_ler(conn, registrada: catalogo.ObraRegistrada) -> str:
        estante.salvar_quero_ler(conn, LEITOR, registrada.obra_id, edicao_id=registrada.edicao_id)
        item = estante.quero_ler_da_obra(conn, LEITOR, registrada.obra_id)
        return f"{item.titulo} entrou na sua lista Quero ler."

    _gravar(estado, r, escolha, em_quero_ler)


# --- Embedding de uma Obra do Leitor, na hora (SPEC §7.3) ---


@st.cache_resource(show_spinner="Carregando o modelo de embedding…")
def _codificador(nome: str) -> recomendacao.Codificador:
    return recomendacao.carregar_codificador(nome)


def calcular_parecidos(obra_id: int) -> None:
    """Depois de salvar a Leitura, numa transação à parte: se falhar (GPU ocupada, modelo
    ausente), a Leitura já está salva e a Obra fica para o `atualizar` (SPEC §10)."""
    with recomendacao.transacao() as conn:
        if not recomendacao.pendente(conn, obra_id):
            return
        nome = recomendacao.modelo_de_conteudo_ativo(conn)
    try:
        cod = _codificador(nome)
        with st.spinner("Calculando os parecidos com este livro…"):
            with recomendacao.transacao() as conn:
                recomendacao.calcular_vizinhos_da_obra(conn, obra_id, cod)
    except Exception as e:  # noqa: BLE001 — nada aqui pode desfazer a Leitura salva
        st.caption(f"Os parecidos ficam para a próxima abertura do app ({e.__class__.__name__}).")
        return
    depois_de_gravar()


# --- Sugestões e página da Obra (R4, R5) ---

PAGINA_OBRA = "paginas/obra.py"


def texto_do_motivo(nota: int, titulo: str) -> str:
    """O Motivo em linguagem simples (SPEC §8.5); o domínio entrega só os dados."""
    return f"Porque você deu {nota} a *{titulo}*"


def texto_do_ponto_em_comum(ponto: recomendacao.PontoEmComum | None) -> str | None:
    """O Ponto em comum de um item de "Parecidos com este" (SPEC §8.3)."""
    if ponto is None:
        return None
    if ponto.tipo == "autor":
        return f"Também de {ponto.valores[0]}"
    if ponto.tipo == "temas":
        return "Temas: " + ", ".join(ponto.valores)
    return f"Também {ponto.valores[0]}"


def texto_do_contribuinte(c: recomendacao.Contribuinte) -> str:
    """Uma linha do Motivo detalhado (R11, SPEC §8.6)."""
    return f"*{c.titulo_exibicao}*, sua nota {c.nota}: {round(100 * c.participacao)} %"


def posicao_da_sugestao(obra_id: int) -> int | None:
    """A posição da Obra em "Para você" nesta sessão, se ela veio de lá (O2 e O5)."""
    return st.session_state.get("posicao-da-sugestao", {}).get(obra_id)


def lista_da_sugestao(obra_id: int) -> str | None:
    """A lista de "Para você" (`geral` ou `tecnologia`) de onde a Obra veio (O2, §8.8)."""
    return st.session_state.get("lista-da-sugestao", {}).get(obra_id)


def quero_ler(obra_id: int, titulo: str, chave: str) -> None:
    """O botão "Quero ler" (R8): guarda a Obra na lista e a tira de "Para você"."""
    if not st.button("Quero ler", key=f"{chave}-quero", icon="🔖", use_container_width=True):
        return
    try:
        with estante.transacao() as conn:
            estante.salvar_quero_ler(
                conn, LEITOR, obra_id, posicao_da_sugestao(obra_id), lista_da_sugestao(obra_id)
            )
    except (estante.JaNaEstante, estante.JaEmQueroLer) as e:
        st.warning(str(e), icon="📚")
        return
    depois_de_gravar()
    st.toast(f"{titulo} entrou na sua lista Quero ler.")
    st.rerun()


def tirar_de_quero_ler(obra_id: int, titulo: str, chave: str) -> None:
    if not st.button("Tirar da lista", key=f"{chave}-tirar", use_container_width=True):
        return
    with estante.transacao() as conn:
        estante.tirar_de_quero_ler(conn, LEITOR, obra_id)
    depois_de_gravar()
    st.toast(f"{titulo} saiu da sua lista Quero ler.")
    st.rerun()


def comecei_a_ler(obra_id: int, titulo: str, chave: str) -> None:
    """O botão "Comecei a ler" (R13): põe a Obra em Estou lendo e a tira de Quero ler."""
    if not st.button("Comecei a ler", key=f"{chave}-lendo", icon="📖", use_container_width=True):
        return
    try:
        with estante.transacao() as conn:
            estante.salvar_estou_lendo(conn, LEITOR, obra_id, posicao_da_sugestao(obra_id))
    except estante.JaNaEstante as e:
        st.warning(str(e), icon="📚")
        return
    depois_de_gravar()
    st.toast(f"{titulo} entrou em Estou lendo.")
    st.rerun()


def parei_de_ler(obra_id: int, titulo: str, chave: str) -> None:
    if not st.button("Parei de ler", key=f"{chave}-parei", use_container_width=True):
        return
    with estante.transacao() as conn:
        estante.tirar_de_estou_lendo(conn, LEITOR, obra_id)
    depois_de_gravar()
    st.toast(f"{titulo} saiu de Estou lendo.")
    st.rerun()


def dispensar(obra_id: int, titulo: str, chave: str) -> None:
    """O botão "Não tenho interesse" (R7): a Obra não volta a "Para você"."""
    if not st.button("Não tenho interesse", key=f"{chave}-dispensar", type="tertiary"):
        return
    with estante.transacao() as conn:
        estante.dispensar(
            conn, LEITOR, obra_id, posicao_da_sugestao(obra_id), lista_da_sugestao(obra_id)
        )
    depois_de_gravar()
    st.toast(f"{titulo} não volta mais a Para você.")
    st.rerun()


def desfazer_dispensa(obra_id: int, chave: str) -> None:
    if not st.button("Desfazer", key=f"{chave}-desfazer"):
        return
    with estante.transacao() as conn:
        estante.desfazer_dispensa(conn, LEITOR, obra_id)
    depois_de_gravar()
    st.rerun()


def abrir_obra(obra_id: int, posicao: int | None = None) -> None:
    """Vai para a página da Obra. Vindo de "Para você", registra `sugestao_aberta` (O2)."""
    if posicao is not None:
        with estante.transacao() as conn:
            estante.registrar_evento(conn, LEITOR, "sugestao_aberta", obra_id, posicao=posicao)
        st.session_state.setdefault("posicao-da-sugestao", {})[obra_id] = posicao
    st.switch_page(PAGINA_OBRA, query_params={"obra": str(obra_id)})


def ja_li(obra_id: int, titulo: str, chave: str) -> None:
    """O botão "Já li": abre a Nota e grava a Leitura (R1 + R2 num passo).

    Uma Obra que veio de "Para você" (direto ou pelas listas Quero ler e Estou lendo) entra
    com `origem='sugestao'` e registra `ja_li_de_sugestao` (O5); as demais, com
    `origem='catalogo'`. `estante.adicionar` tira a Obra das duas listas (R8, R13).
    """
    with st.popover("Já li", use_container_width=True, key=f"{chave}-pop"):
        estrelas = st.feedback("stars", key=f"{chave}-nota")
        if not st.button("Salvar na Estante", key=f"{chave}-salvar", type="primary"):
            return
        nota = None if estrelas is None else estrelas + 1
        posicao = posicao_da_sugestao(obra_id)
        try:
            with estante.transacao() as conn:
                estante.adicionar(
                    conn,
                    LEITOR,
                    obra_id,
                    nota,
                    origem="sugestao" if posicao is not None else "catalogo",
                )
                if posicao is not None:
                    estante.registrar_evento(
                        conn, LEITOR, "ja_li_de_sugestao", obra_id, posicao=posicao, nota=nota
                    )
        except estante.JaNaEstante as e:
            st.warning(str(e), icon="📚")
            return
        depois_de_gravar()
        st.toast(f"{titulo} entrou na Estante.")
        st.rerun()
