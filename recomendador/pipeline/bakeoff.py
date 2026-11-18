"""Bake-off do modelo de embedding (SPEC §8.4): o teste entre idiomas e a escolha dos pares.

O teste entre idiomas imita uma Obra do Leitor vinda de uma Edição brasileira: título,
autor e descrição em português, sem tags. Ela tem de cair perto da própria Obra do
Catálogo, cujo texto é em inglês: a Obra precisa estar entre os 3 vizinhos mais próximos.

Os pares ficam em `tests/dados/pares_pt_en.yaml` só com identificadores, porque o
repositório é público e as descrições são textos das editoras. As descrições ficam no
cache local `data/bakeoff/pares_pt_en.json`, refeito pelo Google Books quando falta.
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import yaml
from sqlalchemy import Connection, text

from recomendador.catalogo.fontes.google_books import GoogleBooks
from recomendador.catalogo.texto import normalizar
from recomendador.recomendacao.embeddings import Codificador
from recomendador.recomendacao.texto import DadosDaObra, texto_da_obra

log = logging.getLogger(__name__)

PARES = 20
TOP = 3
MIN_ACERTOS = 18
MIN_DESCRICAO = 200  # caracteres, para o texto em português ter conteúdo


@dataclass(frozen=True)
class Par:
    goodbooks_book_id: int
    isbn: str
    google_volume_id: str
    titulo: str  # da Edição brasileira
    autores: tuple[str, ...] = ()
    descricao: str = ""  # só no cache local

    def texto(self) -> str:
        return texto_da_obra(
            DadosDaObra(titulo=self.titulo, autores=self.autores, descricao=self.descricao)
        )


@dataclass(frozen=True)
class ResultadoEntreIdiomas:
    acertos: int
    total: int
    posicoes: dict[int, int | None]  # goodbooks_book_id → posição da própria Obra (1 = primeira)

    @property
    def passou(self) -> bool:
        return self.acertos >= MIN_ACERTOS * self.total / PARES

    def resumo(self) -> str:
        return f"{self.acertos}/{self.total}"


def conferir_entre_idiomas(
    codificador: Codificador,
    pares: Sequence[Par],
    obra_por_gb: dict[int, int],
    ids: np.ndarray,
    embeddings: np.ndarray,
    top: int = TOP,
) -> ResultadoEntreIdiomas:
    """Para cada par, a posição da própria Obra entre os vizinhos do texto em português."""
    e_pt = codificador.codificar([p.texto() for p in pares])
    sims = e_pt @ embeddings.astype(np.float32).T
    posicoes: dict[int, int | None] = {}
    for par, linha in zip(pares, sims, strict=True):
        alvo = obra_por_gb[par.goodbooks_book_id]
        ordem = ids[np.argsort(-linha, kind="stable")[:top]]
        achou = np.flatnonzero(ordem == alvo)
        posicoes[par.goodbooks_book_id] = int(achou[0]) + 1 if len(achou) else None
    acertos = sum(p is not None for p in posicoes.values())
    return ResultadoEntreIdiomas(acertos, len(pares), posicoes)


# --- escolha e cache dos pares ---

_CANDIDATAS = text(
    """
    SELECT o.id, o.goodbooks_book_id, o.autores,
           array_agg(i.isbn13 ORDER BY i.origem, i.isbn13) AS isbns
    FROM obra o JOIN obra_isbn i ON i.obra_id = o.id
    WHERE o.origem = 'base' AND (i.isbn13 LIKE '97885%' OR i.isbn13 LIKE '97865%')
    GROUP BY o.id
    ORDER BY o.popularidade DESC
    LIMIT 300
    """
)


def escolher_pares(conn: Connection, google: GoogleBooks, n: int = PARES) -> list[Par]:
    """As `n` Obras mais populares com uma Edição brasileira cuja descrição o Google Books
    tem em português, no máximo uma por autor."""
    pares: list[Par] = []
    autores_vistos: set[str] = set()
    for obra in conn.execute(_CANDIDATAS):
        autor = normalizar(obra.autores[0]) if obra.autores else ""
        if autor in autores_vistos:
            continue
        for isbn in obra.isbns[:3]:
            r = next(
                (
                    r
                    for r in google.buscar(isbn)
                    if r.idioma == "pt" and isbn in r.isbns and r.google_volume_id
                ),
                None,
            )
            if r and r.descricao and len(r.descricao) >= MIN_DESCRICAO:
                pares.append(
                    Par(
                        obra.goodbooks_book_id,
                        isbn,
                        r.google_volume_id,
                        r.titulo,
                        tuple(r.autores),
                        r.descricao,
                    )
                )
                autores_vistos.add(autor)
                log.info("Par %d: %s (%s)", len(pares), r.titulo, isbn)
                break
        if len(pares) == n:
            break
    return pares


def gravar_pares(pares: Sequence[Par], arquivo_yaml: Path, cache: Path) -> None:
    ids = [
        {
            k: v
            for k, v in asdict(p).items()
            if k in ("goodbooks_book_id", "isbn", "google_volume_id", "titulo")
        }
        for p in pares
    ]
    cabecalho = (
        "# Pares do teste entre idiomas do bake-off (SPEC §8.4), gerados por\n"
        "# `python -m recomendador bakeoff --refazer-pares`. Só identificadores: as descrições\n"
        "# (das editoras) ficam no cache local data/bakeoff/pares_pt_en.json.\n"
    )
    texto = yaml.safe_dump(ids, allow_unicode=True, sort_keys=False)
    arquivo_yaml.write_bytes((cabecalho + texto).encode("utf-8"))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(
        json.dumps([asdict(p) for p in pares], ensure_ascii=False, indent=1).encode("utf-8")
    )


def carregar_pares(arquivo_yaml: Path, cache: Path, google: GoogleBooks | None) -> list[Par]:
    """Os pares do YAML, com a descrição do cache (ou do Google Books, se faltar)."""
    ids = yaml.safe_load(arquivo_yaml.read_text(encoding="utf-8"))
    guardados = (
        {p["goodbooks_book_id"]: p for p in json.loads(cache.read_text(encoding="utf-8"))}
        if cache.exists()
        else {}
    )
    pares = []
    for item in ids:
        g = guardados.get(item["goodbooks_book_id"])
        if g is None:
            if google is None:
                raise FileNotFoundError(f"Sem a descrição de {item['titulo']} em {cache}")
            r = next(r for r in google.buscar(item["isbn"]) if item["isbn"] in r.isbns)
            g = {**item, "autores": list(r.autores), "descricao": r.descricao or ""}
        pares.append(
            Par(
                g["goodbooks_book_id"],
                g["isbn"],
                g["google_volume_id"],
                g["titulo"],
                tuple(g.get("autores") or ()),
                g.get("descricao") or "",
            )
        )
    if len(guardados) < len(pares):
        gravar_pares(pares, arquivo_yaml, cache)
    return pares
