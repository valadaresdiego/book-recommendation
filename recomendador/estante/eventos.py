"""Eventos que medem as metas do PRD §7 (SPEC §7.6). As consultas estão em
`reports/consultas-metricas.sql`."""

import json
import uuid

from sqlalchemy import Connection, text

TIPOS_DE_EVENTO = frozenset(
    {
        "busca_iniciada",  # {texto}: início do O3
        "leitura_salva",  # {origem, duracao_s, com_nota}: O3
        "nota_alterada",  # {de, para}
        "leitura_removida",  # {nota}
        "sugestao_exibida",  # {posicao, pontuacao, motivo_obra_id, execucoes}: O2
        "sugestao_aberta",  # {posicao}: O2
        "ja_li_de_sugestao",  # {posicao, nota}: O5
        "montagem_pulada",  # {}: o Leitor clicou em "Pular" na Montagem da Estante
        "sugestao_dispensada",  # {posicao}: O2 (R7)
        "quero_ler_salvo",  # {posicao}: O2 (R8)
    }
)


def registrar_evento(
    conn: Connection, leitor_id: uuid.UUID, tipo: str, obra_id: int | None = None, **dados
) -> None:
    if tipo not in TIPOS_DE_EVENTO:
        raise ValueError(f"Tipo de evento desconhecido: {tipo}")
    conn.execute(
        text(
            "INSERT INTO evento (leitor_id, tipo, obra_id, dados) "
            "VALUES (:l, :t, :o, CAST(:d AS jsonb))"
        ),
        {"l": leitor_id, "t": tipo, "o": obra_id, "d": json.dumps(dados, ensure_ascii=False)},
    )


def evento_registrado(conn: Connection, leitor_id: uuid.UUID, tipo: str) -> bool:
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM evento WHERE leitor_id = :l AND tipo = :t)"),
        {"l": leitor_id, "t": tipo},
    ).scalar_one()
