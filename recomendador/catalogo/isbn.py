"""Normalização de ISBN. Todo ISBN guardado no banco é ISBN-13, só dígitos."""

import re

_SEPARADORES = re.compile(r"[\s\-]")


def _digito_isbn13(doze: str) -> str:
    soma = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(doze))
    return str((10 - soma % 10) % 10)


def _isbn10_valido(isbn10: str) -> bool:
    valores = [10 if c == "X" else int(c) for c in isbn10]
    return sum(v * (10 - i) for i, v in enumerate(valores)) % 11 == 0


def completar_isbn13(doze: str) -> str:
    """Acrescenta o dígito verificador aos 12 primeiros dígitos de um ISBN-13."""
    return doze + _digito_isbn13(doze)


def isbn10_para_13(isbn10: str) -> str:
    return completar_isbn13("978" + isbn10[:9])


def normalizar_isbn(valor: str | None) -> str | None:
    """ISBN-10 ou ISBN-13, com ou sem hífens, vira ISBN-13. Inválido vira None."""
    if not valor:
        return None
    limpo = _SEPARADORES.sub("", valor).upper()
    if re.fullmatch(r"\d{9}[\dX]", limpo):
        return isbn10_para_13(limpo) if _isbn10_valido(limpo) else None
    if re.fullmatch(r"97[89]\d{10}", limpo):
        return limpo if _digito_isbn13(limpo[:12]) == limpo[12] else None
    return None


def parece_isbn(texto: str) -> bool:
    """Texto com só dígitos e hífens, de 10 ou 13 dígitos (SPEC §7.1)."""
    limpo = _SEPARADORES.sub("", texto).upper()
    return bool(re.fullmatch(r"\d{9}[\dX]|\d{13}", limpo))
