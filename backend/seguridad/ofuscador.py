import re

RUT_PATTERN = re.compile(
    r"(?<![\w])(?:\d{1,2}\.?\d{3}\.?\d{3}-?[0-9kK])(?!(?:[\w]|\.))",
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(
    r"(?<![\w])(?:[A-Za-z0-9._%+-]+)@(?:[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w])",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+?56\s*[-.]?\s*)?(?:9|\d{1,2})\s*\d{7,8}(?!\w)",
    re.IGNORECASE,
)


def _es_rut_valido(rut: str) -> bool:
    """Valida un RUT chileno simple, sin depender de bibliotecas externas."""
    rut = rut.strip().replace(".", "").replace("-", "")
    if len(rut) < 8 or len(rut) > 9:
        return False
    cuerpo = rut[:-1]
    dv = rut[-1].upper()
    if not cuerpo.isdigit():
        return False
    suma = 0
    multiplo = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplo
        multiplo += 1
        if multiplo == 8:
            multiplo = 2
    resto = suma % 11
    dv_calculado = 11 - resto
    if dv_calculado == 11:
        dv_esperado = "0"
    elif dv_calculado == 10:
        dv_esperado = "K"
    else:
        dv_esperado = str(dv_calculado)
    return dv == dv_esperado


def enmascarar_datos_sensibles(texto):
    """Anonimiza PII antes de persistir o registrar un texto de usuario."""
    if texto is None:
        return texto

    texto_str = str(texto)

    def reemplazar_rut(match):
        rut = match.group(0)
        return "[RUT_OCULTO]" if _es_rut_valido(rut) else rut

    texto_str = RUT_PATTERN.sub(reemplazar_rut, texto_str)
    texto_str = EMAIL_PATTERN.sub("[EMAIL_OCULTO]", texto_str)
    texto_str = PHONE_PATTERN.sub("[TELEFONO_OCULTO]", texto_str)
    return texto_str
