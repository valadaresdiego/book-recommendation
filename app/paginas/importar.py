"""Importar (R9, SPEC §8.9): CSV do Goodreads → prévia → importar → revisão das falhas."""

import streamlit as st
from componentes import (
    LEITOR,
    autores_em_texto,
    calcular_parecidos,
    depois_de_gravar,
    e_uma_destas,
    esquecer_e_uma_destas,
)

from recomendador import catalogo, estante

PREVIA = "importar-previa"
RELATORIO = "importar-relatorio"
PENDENTES = "importar-pendentes"
PULADAS = "importar-puladas"
AVISO = "importar-aviso"

_ESTADO = {"lida": "lida", "lendo": "lendo", "quero_ler": "quero ler"}
_DESTINO = {
    "estante": "entrou na Estante",
    "quero_ler": "entrou em Quero ler",
    "estou_lendo": "entrou em Estou lendo",
    "ja_na_estante": "já estava na Estante e não mudou",
    "ja_na_lista": "já estava na lista e não mudou",
}


def _recomecar() -> None:
    for linha in st.session_state.get(PENDENTES, []):
        esquecer_e_uma_destas(_prefixo(linha))
    for chave in (PREVIA, RELATORIO, PENDENTES, PULADAS, AVISO):
        st.session_state.pop(chave, None)
    st.session_state["importar-arquivo-n"] = st.session_state.get("importar-arquivo-n", 0) + 1


def _prefixo(r: estante.LinhaResolvida) -> str:
    return f"importar-{r.linha.numero}"


def _qtd(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _descricao(linha: estante.LinhaImportada) -> str:
    nota = f"nota {linha.nota}" if linha.nota else "sem nota"
    estado = _ESTADO.get(linha.estado or "", linha.prateleira or "sem prateleira")
    return f"**{linha.titulo}** — {autores_em_texto(linha.autores)}  \n{estado} · {nota}"


# --- 1. Arquivo e prévia ---


def _analisar(conteudo: bytes) -> None:
    try:
        linhas = estante.ler_goodreads(conteudo)
    except estante.ArquivoInvalido as e:
        st.error(str(e))
        return
    if not linhas:
        st.warning("O arquivo não tem nenhuma linha.")
        return
    barra = st.progress(0.0, text="Identificando as Obras…")

    def avancar(feitas: int, total: int) -> None:
        barra.progress(feitas / total, text=f"Identificando as Obras… {feitas} de {total}")

    with estante.transacao() as conn:
        previa = estante.preparar_importacao(
            conn, LEITOR, linhas, catalogo.open_library(), ao_avancar=avancar
        )
    st.session_state[PREVIA] = previa
    st.rerun()


def _mostrar_previa(previa: estante.Previa) -> None:
    encontradas, sem = len(previa.encontradas), len(previa.sem_correspondencia)
    a, b, c, d = st.columns(4)
    a.metric("Linhas", previa.linhas)
    b.metric("Encontradas", encontradas, help="A Obra está no Catálogo")
    c.metric("Para revisar", sem, help="Sem correspondência no Catálogo")
    d.metric("Ignoradas", len(previa.ignoradas), help="Outras prateleiras")
    st.caption(
        f"{round(100 * previa.taxa)} % das linhas lidas, em leitura ou em Quero ler acharam a "
        "Obra. As sem correspondência vão para a revisão, depois da importação."
    )
    if previa.ja_na_estante:
        n = previa.ja_na_estante
        st.caption(
            "1 Obra encontrada já está na sua Estante e não muda."
            if n == 1
            else f"{n} Obras encontradas já estão na sua Estante e não mudam."
        )
    if previa.ignoradas:
        with st.expander(f"Linhas ignoradas ({len(previa.ignoradas)})"):
            st.caption("Só entram as prateleiras read, currently-reading e to-read.")
            for linha in previa.ignoradas:
                st.markdown(_descricao(linha))

    importar, cancelar = st.columns(2)
    rotulo = "Importar" if encontradas else "Revisar as sem correspondência"
    if importar.button(rotulo, type="primary", use_container_width=True):
        with estante.transacao() as conn:
            relatorio = estante.importar(conn, LEITOR, previa)
        depois_de_gravar()
        st.session_state[RELATORIO] = relatorio
        st.session_state[PENDENTES] = list(previa.sem_correspondencia)
        st.session_state[PULADAS] = []
        st.session_state.pop(PREVIA)
        st.rerun()
    if cancelar.button("Cancelar", use_container_width=True):
        _recomecar()
        st.rerun()


# --- 2. Relatório ---


def _mostrar_relatorio(r: estante.Relatorio) -> None:
    partes = [f"{_qtd(r.leituras, 'Leitura', 'Leituras')} na Estante"]
    if r.quero_ler:
        partes.append(f"{r.quero_ler} em Quero ler")
    if r.estou_lendo:
        partes.append(f"{r.estou_lendo} em Estou lendo")
    if r.leituras or r.quero_ler or r.estou_lendo:
        st.success("Importação feita: " + ", ".join(partes) + ".", icon="✅")
    else:
        st.info("Nada novo: as Obras encontradas já estavam na Estante ou nas listas.", icon="👍")
    detalhes = []
    if r.repetidas:
        n = _qtd(r.repetidas, "linha repetia", "linhas repetiam")
        detalhes.append(f"{n} a Obra de outra linha")
    if r.ja_na_lista:
        n = _qtd(r.ja_na_lista, "Obra já estava", "Obras já estavam")
        detalhes.append(f"{n} em Quero ler ou Estou lendo")
    if r.ignoradas:
        n = _qtd(
            r.ignoradas, "linha de outra prateleira ficou", "linhas de outras prateleiras ficaram"
        )
        detalhes.append(f"{n} de fora")
    if detalhes:
        st.caption("; ".join(detalhes) + ".")
    if r.ja_na_estante:
        diferentes = [
            j for j in r.ja_na_estante if j.nota_arquivo and j.nota_arquivo != j.nota_estante
        ]
        with st.expander(
            f"Já estavam na Estante ({len(r.ja_na_estante)}), "
            f"{len(diferentes)} com outra nota no arquivo"
        ):
            st.caption("Vale a nota da Estante. Para mudar, edite na Estante.")
            for j in diferentes:
                atual = j.nota_estante or "sem nota"
                st.markdown(f"*{j.titulo}*: na Estante {atual}, no arquivo {j.nota_arquivo}")


# --- 3. Revisão das linhas sem correspondência ---


def _gravar_linha(
    pendente: estante.LinhaResolvida,
    r: catalogo.Resolucao,
    escolha: int | None,
    original: str | None,
) -> None:
    with estante.transacao() as conn:
        if escolha is None and original:
            r = catalogo.informar_titulo_original(conn, r, original)
        desfecho = estante.importar_linha(
            conn, LEITOR, estante.LinhaResolvida(pendente.linha, r), escolha=escolha
        )
    depois_de_gravar()
    calcular_parecidos(desfecho.obra_id)
    st.session_state[AVISO] = f"{pendente.linha.titulo} {_DESTINO[desfecho.destino]}."
    _tirar(pendente)


def _tirar(pendente: estante.LinhaResolvida, pular: bool = False) -> None:
    esquecer_e_uma_destas(_prefixo(pendente))
    st.session_state[PENDENTES].remove(pendente)
    if pular:
        st.session_state[PULADAS].append(pendente.linha)
    st.rerun()


def _revisar() -> None:
    pendentes: list[estante.LinhaResolvida] = st.session_state.get(PENDENTES, [])
    puladas: list[estante.LinhaImportada] = st.session_state.get(PULADAS, [])
    if aviso := st.session_state.pop(AVISO, None):
        st.toast(aviso)
    if pendentes:
        st.subheader(f"Sem correspondência: {len(pendentes)} para revisar")
        pendente = pendentes[0]
        with st.container(border=True):
            st.markdown(_descricao(pendente.linha))
            st.caption(f"Linha {pendente.linha.numero} do arquivo")
            r, escolha, original = e_uma_destas(_prefixo(pendente), pendente.resolucao)
            if r.obra_nova is not None and escolha is None:
                st.caption("Sem escolher uma candidata, a Obra entra como nova no Catálogo.")
            importar, pular = st.columns(2)
            if importar.button("Importar", type="primary", use_container_width=True):
                _gravar_linha(pendente, r, escolha, original)
            if pular.button("Pular", use_container_width=True):
                _tirar(pendente, pular=True)
        if len(pendentes) > 1:
            with st.expander("As próximas"):
                for p in pendentes[1:]:
                    st.markdown(_descricao(p.linha))
    elif st.session_state.get(RELATORIO) is not None:
        st.info("Nenhuma linha falta revisar.", icon="👍")
    if puladas:
        with st.expander(f"Puladas ({len(puladas)})", expanded=not pendentes):
            st.caption(
                "Adicione à mão pela busca ou importe o mesmo arquivo de novo: o que já "
                "entrou é pulado."
            )
            for linha in puladas:
                st.markdown(_descricao(linha))


# --- Página ---

st.title("Importar")
st.caption(
    "Traga o seu histórico do Goodreads: em My Books → Import and export, clique em "
    "Export Library e envie aqui o CSV. Vale o que já está na sua Estante."
)

if st.session_state.get(RELATORIO) is None:
    arquivo = st.file_uploader(
        "CSV exportado do Goodreads",
        type="csv",
        key=f"importar-arquivo-{st.session_state.get('importar-arquivo-n', 0)}",
        on_change=lambda: st.session_state.pop(PREVIA, None),  # outro arquivo, outra prévia
    )
    previa = st.session_state.get(PREVIA)
    if previa is None:
        if arquivo is not None and st.button("Analisar", type="primary"):
            _analisar(arquivo.getvalue())
    else:
        _mostrar_previa(previa)
else:
    _mostrar_relatorio(st.session_state[RELATORIO])
    _revisar()
    if st.button("Importar outro arquivo"):
        _recomecar()
        st.rerun()
