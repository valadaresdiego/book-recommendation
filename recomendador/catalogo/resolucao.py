"""Resolução Edição → Obra (SPEC §7.2).

`resolver_obra` só lê (o banco e a Open Library): aplica as regras 1 a 4 na ordem e devolve
a Obra encontrada ou, na regra 4, a proposta de uma Obra nova com as candidatas para a
pergunta "É uma destas?". Nada é gravado até o Leitor confirmar: `registrar_resolucao`
grava a Edição e, se for o caso, a Obra nova (ou usa a candidata que ele escolheu). Assim
uma busca abandonada no meio não deixa Obra órfã no Catálogo.
"""

import logging
from dataclasses import dataclass, replace

from rapidfuzz import fuzz
from sqlalchemy import Connection, text

from recomendador.catalogo.busca import buscar_no_catalogo
from recomendador.catalogo.fontes import FonteIndisponivel
from recomendador.catalogo.fontes.open_library import EdicaoOL, ObraOL, OpenLibrary
from recomendador.catalogo.texto import normalizar, sobrenome
from recomendador.catalogo.tipos import Candidata, ObraProposta, Resolucao, ResultadoBusca

log = logging.getLogger(__name__)

SEMELHANCA_TITULO_MINIMA = 90  # rapidfuzz.token_set_ratio, regra 3
MAX_CANDIDATAS = 5
_CANDIDATAS_DA_REGRA_3 = 50


@dataclass(frozen=True)
class ObraRegistrada:
    obra_id: int
    edicao_id: int | None


# --- Regras ---


def _por_isbn(conn: Connection, isbns: tuple[str, ...]) -> int | None:
    if not isbns:
        return None
    return conn.execute(
        text(
            "SELECT obra_id FROM obra_isbn WHERE isbn13 = ANY(:i) "
            "ORDER BY array_position(CAST(:i AS text[]), CAST(isbn13 AS text)) LIMIT 1"
        ),
        {"i": list(isbns)},
    ).scalar()


def _por_work(conn: Connection, works: list[str]) -> int | None:
    if not works:
        return None
    return conn.execute(
        text("SELECT id FROM obra WHERE ol_work_key = ANY(:w) LIMIT 1"), {"w": works}
    ).scalar()


def _consultar_open_library(
    ol: OpenLibrary | None, isbns: tuple[str, ...]
) -> tuple[EdicaoOL | None, ObraOL | None]:
    """A primeira Edição da OL entre os ISBNs e a work dela. OL fora do ar: (None, None)."""
    if ol is None:
        return None, None
    try:
        edicao = next((e for i in isbns if (e := ol.edicao_por_isbn(i))), None)
        obra = ol.obra(edicao.works[0]) if edicao and edicao.works else None
    except FonteIndisponivel as e:
        log.warning("Resolução sem a Open Library: %s", e)
        return None, None
    return edicao, obra


def _por_titulo_original(
    conn: Connection, titulos: list[str], autores: tuple[str, ...]
) -> int | None:
    """Regra 3: título (token_set_ratio ≥ 90) e o último sobrenome do 1º autor iguais."""
    alvo = sobrenome(autores[0]) if autores else None
    titulos = list(dict.fromkeys(t for t in map(normalizar, titulos) if t))
    if not alvo or not titulos:
        return None
    melhor: tuple[float, float, int, int] | None = None
    for titulo in titulos:
        linhas = conn.execute(
            text(
                """
                SELECT o.id, o.titulo, o.titulo_original, o.autores, o.popularidade
                FROM obra o
                WHERE normalizar_busca(:t) <% obra_texto_busca(
                    o.titulo, o.titulo_original, o.titulo_exibicao, o.autores)
                ORDER BY word_similarity(normalizar_busca(:t), obra_texto_busca(
                    o.titulo, o.titulo_original, o.titulo_exibicao, o.autores)) DESC
                LIMIT :n
                """
            ),
            {"t": titulo, "n": _CANDIDATAS_DA_REGRA_3},
        )
        for o in linhas:
            if not o.autores or sobrenome(o.autores[0]) != alvo:
                continue
            for do_catalogo in filter(None, (o.titulo, o.titulo_original)):
                do_catalogo = normalizar(do_catalogo)
                conjunto = fuzz.token_set_ratio(titulo, do_catalogo)
                if conjunto < SEMELHANCA_TITULO_MINIMA:
                    continue
                # token_set_ratio dá 100 para "dune" × "dune messiah": o ratio simples desempata.
                chave = (conjunto, fuzz.ratio(titulo, do_catalogo), o.popularidade, -o.id)
                if melhor is None or chave > melhor:
                    melhor = chave
    return -melhor[3] if melhor else None


def _candidatas(conn: Connection, titulo: str, autores: tuple[str, ...]) -> tuple[Candidata, ...]:
    """As 5 Obras do Catálogo mais próximas por trigram de título e autor."""
    texto = f"{titulo} {autores[0] if autores else ''}"
    return tuple(
        Candidata(r.obra_id, r.titulo, r.autores, r.ano, r.capa_url)
        for r in buscar_no_catalogo(conn, texto, MAX_CANDIDATAS, minima=0)
        if r.obra_id is not None
    )


def _proposta(
    edicao: ResultadoBusca, edicao_ol: EdicaoOL | None, obra_ol: ObraOL | None
) -> ObraProposta:
    titulo_original = (edicao_ol.traducao_de if edicao_ol else None) or (
        edicao_ol.titulos_da_obra[0] if edicao_ol and edicao_ol.titulos_da_obra else None
    )
    titulo = (obra_ol.titulo if obra_ol else None) or titulo_original or edicao.titulo
    em_portugues = edicao.idioma == "pt" or (edicao_ol is not None and "por" in edicao_ol.idiomas)
    return ObraProposta(
        titulo=titulo,
        titulo_original=titulo_original,
        titulo_exibicao=edicao.titulo if em_portugues else titulo,
        autores=edicao.autores,
        ano_original=(obra_ol.ano if obra_ol else None) or edicao.ano,
        descricao=(obra_ol.descricao if obra_ol else None) or edicao.descricao,
        capa_url=edicao.capa_url
        or (edicao_ol.capa_url if edicao_ol else None)
        or (obra_ol.capa_url if obra_ol else None),
        ol_work_key=obra_ol.chave if obra_ol else None,
        assuntos=obra_ol.assuntos if obra_ol else (),
        isbns=edicao.isbns,
        enriquecida=obra_ol is not None,
    )


def resolver_obra(conn: Connection, resultado: ResultadoBusca, ol: OpenLibrary | None) -> Resolucao:
    """Aplica as regras do SPEC §7.2 ao resultado escolhido na busca. Não grava nada."""
    edicao = resultado if resultado.google_volume_id else None
    if resultado.obra_id is not None:
        return Resolucao("catalogo", edicao, obra_id=resultado.obra_id)

    if obra_id := _por_isbn(conn, resultado.isbns):
        return Resolucao("isbn", edicao, obra_id=obra_id)

    edicao_ol, obra_ol = _consultar_open_library(ol, resultado.isbns)
    chave_ol = edicao_ol.chave if edicao_ol else None
    works = [*(edicao_ol.works[:1] if edicao_ol else ()), *([obra_ol.chave] if obra_ol else ())]
    if obra_id := _por_work(conn, works):
        return Resolucao("ol_work", edicao, obra_id=obra_id, edicao_ol=chave_ol)

    titulos = [
        *([edicao_ol.traducao_de] if edicao_ol and edicao_ol.traducao_de else []),
        *(edicao_ol.titulos_da_obra if edicao_ol else ()),
        *([obra_ol.titulo] if obra_ol else []),
        # O título da própria Edição cobre as Edições no idioma original.
        resultado.titulo,
    ]
    if obra_id := _por_titulo_original(conn, titulos, resultado.autores):
        return Resolucao("titulo_original", edicao, obra_id=obra_id, edicao_ol=chave_ol)

    proposta = _proposta(resultado, edicao_ol, obra_ol)
    return Resolucao(
        "nova",
        edicao,
        obra_nova=proposta,
        candidatas=_candidatas(conn, proposta.titulo_exibicao, proposta.autores),
        edicao_ol=chave_ol,
    )


def resolver_manual(conn: Connection, titulo: str, autor: str) -> Resolucao:
    """Cadastro manual (R1, história 11): regras 3 e 4 com o texto digitado."""
    titulo, autor = " ".join(titulo.split()), " ".join(autor.split())
    autores = (autor,) if autor else ()
    if obra_id := _por_titulo_original(conn, [titulo], autores):
        return Resolucao("titulo_original", None, obra_id=obra_id)
    proposta = ObraProposta(
        titulo=titulo,
        titulo_original=None,
        titulo_exibicao=titulo,
        autores=autores,
        ano_original=None,
        descricao=None,
        capa_url=None,
        ol_work_key=None,
    )
    return Resolucao(
        "nova", None, obra_nova=proposta, candidatas=_candidatas(conn, titulo, autores)
    )


def informar_titulo_original(conn: Connection, resolucao: Resolucao, titulo: str) -> Resolucao:
    """O Leitor informa à mão o título original de uma Obra nova (R1, regra 4).

    Reaplica a regra 3 com esse título e os autores da proposta: se casar, a Edição vai para
    a Obra do Catálogo; se não, a proposta guarda o título original.
    """
    titulo = " ".join(titulo.split())
    if resolucao.obra_nova is None or not titulo:
        return resolucao
    if obra_id := _por_titulo_original(conn, [titulo], resolucao.obra_nova.autores):
        return replace(
            resolucao, confianca="titulo_original", obra_id=obra_id, obra_nova=None, candidatas=()
        )
    return replace(resolucao, obra_nova=replace(resolucao.obra_nova, titulo_original=titulo))


# --- Gravação ---


def _inserir_obra(conn: Connection, p: ObraProposta) -> int:
    work = p.ol_work_key
    if work and _por_work(conn, [work]):
        work = None  # outra Obra já tem esta work (UNIQUE)
    obra_id = conn.execute(
        text(
            """
            INSERT INTO obra (titulo, titulo_original, titulo_exibicao, autores, ano_original,
                              descricao, capa_url, origem, ol_work_key, enriquecida_em)
            VALUES (:titulo, :original, :exibicao, :autores, :ano, :descricao, :capa, 'leitor',
                    :work, CASE WHEN :enriquecida THEN now() END)
            RETURNING id
            """
        ),
        {
            "titulo": p.titulo,
            "original": p.titulo_original,
            "exibicao": p.titulo_exibicao,
            "autores": list(p.autores),
            "ano": p.ano_original,
            "descricao": p.descricao,
            "capa": p.capa_url,
            "work": work,
            "enriquecida": p.enriquecida,
        },
    ).scalar_one()
    if p.assuntos:
        conn.execute(
            text(
                "INSERT INTO obra_tag (obra_id, tag, contagem) VALUES (:o, :t, 0) "
                "ON CONFLICT DO NOTHING"
            ),
            [{"o": obra_id, "t": t} for t in p.assuntos],
        )
    return obra_id


def _gravar_edicao(
    conn: Connection, obra_id: int, edicao: ResultadoBusca, chave_ol: str | None
) -> int:
    return conn.execute(
        text(
            """
            INSERT INTO edicao (obra_id, google_volume_id, ol_edition_key, isbn13, titulo,
                                autores, editora, ano, idioma, capa_url)
            VALUES (:obra, :volume, :ol, :isbn, :titulo, :autores, :editora, :ano, :idioma, :capa)
            ON CONFLICT (google_volume_id) DO UPDATE SET
                obra_id = EXCLUDED.obra_id,
                ol_edition_key = coalesce(EXCLUDED.ol_edition_key, edicao.ol_edition_key)
            RETURNING id
            """
        ),
        {
            "obra": obra_id,
            "volume": edicao.google_volume_id,
            "ol": chave_ol,
            "isbn": edicao.isbns[0] if edicao.isbns else None,
            "titulo": edicao.titulo,
            "autores": list(edicao.autores),
            "editora": edicao.editora,
            "ano": edicao.ano,
            "idioma": edicao.idioma,
            "capa": edicao.capa_url,
        },
    ).scalar_one()


def registrar_resolucao(
    conn: Connection, resolucao: Resolucao, escolha: int | None = None
) -> ObraRegistrada:
    """Grava o que a resolução decidiu, quando o Leitor confirma.

    `escolha` é a candidata que o Leitor apontou em "É uma destas?" (só na regra 4);
    sem ela, a regra 4 cria a Obra `origem='leitor'`. A Edição escolhida é gravada em
    `edicao`, os ISBNs dela passam a apontar para a Obra com origem `leitor` (a próxima
    busca resolve pela regra 1, e o `enriquecer-ol` não os apaga; um ISBN que já estava
    lá com origem `open_library` também passa a ser do Leitor) e, se a Edição é em
    português e a Obra ainda não tem título em português,
    o título dela vira o `titulo_exibicao`.
    """
    if escolha is not None:
        if escolha not in {c.obra_id for c in resolucao.candidatas}:
            raise ValueError(f"A Obra {escolha} não é uma das candidatas da resolução")
        obra_id = escolha
    elif resolucao.obra_id is not None:
        obra_id = resolucao.obra_id
    elif resolucao.obra_nova is not None:
        obra_id = _inserir_obra(conn, resolucao.obra_nova)
    else:
        raise ValueError("Resolução sem Obra encontrada nem Obra nova")

    edicao = resolucao.edicao
    if edicao is None or not edicao.google_volume_id:
        return ObraRegistrada(obra_id, None)

    edicao_id = _gravar_edicao(conn, obra_id, edicao, resolucao.edicao_ol)
    if edicao.isbns:
        conn.execute(
            text(
                "INSERT INTO obra_isbn (isbn13, obra_id, origem) VALUES (:i, :o, 'leitor') "
                "ON CONFLICT (isbn13) DO UPDATE SET obra_id = :o, origem = 'leitor' "
                "WHERE obra_isbn.origem = 'open_library'"
            ),
            [{"i": i, "o": obra_id} for i in edicao.isbns],
        )
    if edicao.idioma == "pt":
        conn.execute(
            text(
                "UPDATE obra SET titulo_exibicao = :t "
                "WHERE id = :o AND titulo_exibicao = titulo AND titulo <> :t"
            ),
            {"t": edicao.titulo, "o": obra_id},
        )
    return ObraRegistrada(obra_id, edicao_id)
