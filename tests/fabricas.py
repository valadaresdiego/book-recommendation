"""Criação de Obras, Gêneros e afins para os testes, direto no banco de teste."""

from sqlalchemy import Connection, text


def criar_obra(
    conexao: Connection,
    titulo: str,
    autores: tuple[str, ...] = (),
    *,
    titulo_exibicao: str | None = None,
    titulo_original: str | None = None,
    isbns: tuple[str, ...] = (),
    ol_work_key: str | None = None,
    popularidade: int = 0,
    origem: str = "base",
    ano: int | None = None,
    capa_url: str | None = None,
) -> int:
    obra_id = conexao.execute(
        text(
            """
            INSERT INTO obra (titulo, titulo_original, titulo_exibicao, autores, ano_original,
                              capa_url, origem, ol_work_key, popularidade)
            VALUES (:titulo, :original, :exibicao, :autores, :ano, :capa, :origem, :work, :pop)
            RETURNING id
            """
        ),
        {
            "titulo": titulo,
            "original": titulo_original,
            "exibicao": titulo_exibicao or titulo,
            "autores": list(autores),
            "ano": ano,
            "capa": capa_url,
            "origem": origem,
            "work": ol_work_key,
            "pop": popularidade,
        },
    ).scalar_one()
    for isbn in isbns:
        conexao.execute(
            text("INSERT INTO obra_isbn (isbn13, obra_id, origem) VALUES (:i, :o, :g)"),
            {"i": isbn, "o": obra_id, "g": "base" if origem == "base" else "leitor"},
        )
    return obra_id


def criar_edicao(
    conexao: Connection, obra_id: int, titulo: str, capa_url: str | None = None
) -> int:
    return conexao.execute(
        text(
            "INSERT INTO edicao (obra_id, titulo, capa_url, idioma) "
            "VALUES (:o, :t, :c, 'pt') RETURNING id"
        ),
        {"o": obra_id, "t": titulo, "c": capa_url},
    ).scalar_one()


def criar_genero(conexao: Connection, slug: str, nome: str | None = None) -> int:
    return conexao.execute(
        text("INSERT INTO genero (slug, nome) VALUES (:s, :n) RETURNING id"),
        {"s": slug, "n": nome or slug.capitalize()},
    ).scalar_one()


def ligar_genero(conexao: Connection, obra_id: int, genero_id: int, forca: float = 1.0) -> None:
    conexao.execute(
        text("INSERT INTO obra_genero (obra_id, genero_id, forca) VALUES (:o, :g, :f)"),
        {"o": obra_id, "g": genero_id, "f": forca},
    )


def linha(conexao: Connection, tabela: str, id_: int) -> dict:
    return dict(
        conexao.execute(text(f"SELECT * FROM {tabela} WHERE id = :i"), {"i": id_}).mappings().one()
    )
