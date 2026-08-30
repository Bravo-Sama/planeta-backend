import logging
import re

logger = logging.getLogger("planeta.sanitizador")

_ALERTA_SEGURIDAD = (
    "🚫 Alerta de seguridad: la consulta fue bloqueada porque contiene patrones sospechosos "
    "de Prompt Injection o instrucciones de manipulación del sistema."
)

_PATTERNS = [
    r"ignora\s+(las\s+)?reglas\s+(anteriores|previas|actuales)",
    r"olvida\s+(las\s+)?reglas\s+(anteriores|previas|actuales)",
    r"actua\s+como\s+",
    r"actúa\s+como\s+",
    r"eres\s+ahora\s+",
    r"ignore\s+(all|previous|the)\s+instructions?",
    r"override\s+(the|all|previous)\s+instructions?",
    r"system\s+prompt",
    r"developer\s+prompt",
    r"jailbreak",
    r"prompt\s+injection",
    r"sistema\s+de\s+instrucciones",
    r"sobrescribe\s+(las\s+)?instrucciones",
    r"re-escribe\s+(las\s+)?instrucciones",
    r"haz\s+lo\s+que\s+te\s+diga",
    r"no\s+importa\s+lo\s+que\s+diga\s+antes",
    r"no\s+sigas\s+las\s+reglas",
]


class PromptInjectionException(ValueError):
    """Se lanza cuando la entrada del usuario intenta manipular el sistema."""


def validar_prompt_seguro(texto):
    """Valida la entrada antes de entregarla a LLM o Qdrant."""
    if texto is None:
        return ""

    texto_norm = re.sub(r"\s+", " ", str(texto)).strip()
    if not texto_norm:
        return ""

    texto_lower = texto_norm.lower()
    for patron in _PATTERNS:
        if re.search(patron, texto_lower, flags=re.IGNORECASE):
            logger.warning(
                "Prompt injection detected and blocked. pattern=%s user_input_len=%s",
                patron,
                len(texto_norm),
            )
            raise PromptInjectionException(_ALERTA_SEGURIDAD)

    texto_limpio = re.sub(r"(?i)\b(ignora|olvida|desactiva|anula)\s+(las\s+)?reglas?\b", "", texto_norm)
    texto_limpio = re.sub(r"\s+", " ", texto_limpio).strip()
    if not texto_limpio:
        raise PromptInjectionException(_ALERTA_SEGURIDAD)
    return texto_limpio


def limpiar_entrada(texto):
    """Compatibilidad con el código previo: retorna texto limpio o alerta de seguridad."""
    try:
        return validar_prompt_seguro(texto)
    except PromptInjectionException:
        return _ALERTA_SEGURIDAD
