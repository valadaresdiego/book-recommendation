"""Fusão de uma Obra duplicada na que fica, usada pelas cargas (SPEC §6.1, §8.8)."""

from sqlalchemy import Connection, text

# Tabelas com (leitor_id, obra_id) único: a linha da duplicada só passa se o Leitor ainda
# não tiver uma na que fica.
_UNICAS_POR_LEITOR = ("leitura", "dispensa", "quero_ler", "estou_lendo")


def fundir_obra(conn: Connection, duplicada: int, fica: int) -> None:
    """Funde a Obra `duplicada` na `fica` e apaga a duplicada.

    O que é do Leitor (Leituras, Dispensas, Quero ler, Estou lendo, Edições, Eventos) e os
    ISBNs passam para a que fica; havendo conflito, vale o da que fica. O resto (Vizinhos,
    tags, Gêneros) sai com a Obra, e o próximo cálculo refaz os Vizinhos.
    """
    ids = {"d": duplicada, "f": fica}
    for tabela in _UNICAS_POR_LEITOR:
        conn.execute(
            text(
                f"UPDATE {tabela} t SET obra_id = :f WHERE t.obra_id = :d AND NOT EXISTS ("
                f"SELECT 1 FROM {tabela} x WHERE x.leitor_id = t.leitor_id AND x.obra_id = :f)"
            ),
            ids,
        )
        conn.execute(text(f"DELETE FROM {tabela} WHERE obra_id = :d"), ids)
    for tabela in ("edicao", "evento", "obra_isbn"):
        conn.execute(text(f"UPDATE {tabela} SET obra_id = :f WHERE obra_id = :d"), ids)
    conn.execute(
        text(
            "UPDATE obra SET tem_edicao_pt = true WHERE id = :f AND EXISTS ("
            "SELECT 1 FROM edicao WHERE obra_id = :f AND idioma = 'pt')"
        ),
        ids,
    )
    conn.execute(text("DELETE FROM obra WHERE id = :d"), ids)
