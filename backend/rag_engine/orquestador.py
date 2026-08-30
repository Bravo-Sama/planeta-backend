"""Orquestador principal de consultas de Planeta.

Mantiene un contrato de salida inmutable: todas las rutas devuelven un generador.
La decisión de consulta se envía a RAG o a datos operativos y nunca se adivina
el tipo de retorno del consumidor.
"""

import logging

import requests
from django.conf import settings

from .buscador import hacer_pregunta
from .sanitizador import limpiar_entrada

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
MODELO_CLASIFICACION = settings.MODELO_CLASIFICACION


def _mensaje_ambiguedad():
    """Respuesta de rescate cuando la clasificación del LLM no es confiable."""
    return (
        "El sistema experimenta intermitencias. ¿Su consulta refiere a reglamentación vigente o al estado actual del servicio?"
    )


def _mensaje_operacional_en_desarrollo():
    """Ruta operativa placeholder mientras la capa de base de datos no está conectada."""
    return (
        "⚙️ La capa operativa aún está en desarrollo. La base de datos de métricas y estado del servicio "
        "no está conectada en este momento."
    )


def clasificar_intencion(pregunta_usuario):
    """Clasifica la consulta en NORMATIVA, OPERACIONAL o AMBIGUO usando Llama 3."""
    pregunta_limpia = limpiar_entrada(pregunta_usuario)
    if pregunta_limpia.startswith("🚫"):
        logger.warning("Prompt injection rejected before LLM classification. query_len=%s", len(str(pregunta_usuario)))
        return "SEGURIDAD"

    prompt = f"""
    Eres un clasificador de consultas del sistema Planeta.
    Tu única tarea es decidir si la consulta requiere:
    - NORMATIVA: contenido legal, normativas, resoluciones, requisitos regulatorios, PDFs de Aguas Décimas.
    - OPERACIONAL: métricas, estado del servicio, datos estructurados, reportes, MariaDB, uptime, disponibilidad, incidentes, salud del sistema.

    REGLAS ESTRICTAS:
    1. Responde SOLO con una de estas tres palabras exactas: NORMATIVA, OPERACIONAL o AMBIGUO.
    2. Sin comillas, sin explicación, sin texto extra.
    3. Si la pregunta es ambigua, responde AMBIGUO.

    Pregunta del usuario:
    {pregunta_limpia}
    """

    payload = {
        "model": MODELO_CLASIFICACION,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": 5,
        },
    }

    try:
        respuesta = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=(2, 5))
        if respuesta.status_code != 200:
            logger.error(
                "LLM classification returned non-200 status. status=%s trace=[ERR_LLM_CLASS_TIMEOUT]",
                respuesta.status_code,
            )
            return "AMBIGUO"

        texto = respuesta.json().get("response", "").strip().upper()
        if texto in {"NORMATIVA", "OPERACIONAL", "AMBIGUO"}:
            return texto

        logger.error(
            "LLM classification response malformed. response=%s trace=[ERR_LLM_CLASS_PARSE]",
            texto or "<empty>",
        )
        return "AMBIGUO"

    except requests.exceptions.RequestException as exc:
        logger.error(
            "LLM classification request failed. error=%s trace=[ERR_LLM_CLASS_TIMEOUT]",
            str(exc),
        )
        return "AMBIGUO"
    except Exception as exc:
        logger.error(
            "Unexpected LLM classification failure. error=%s trace=[ERR_LLM_CLASS_PARSE]",
            str(exc),
        )
        return "AMBIGUO"


def procesar_consulta_orquestada(pregunta_usuario, chat_id):
    """Orquesta la consulta y siempre devuelve un generador.

    Esta función preserva un contrato inmutable para el consumidor: nunca emite un
    string plano fuera del flujo iterable. Si la ruta es RAG, usa `yield from`; si
    es operativa o ambigua, usa `yield` con el mensaje final ya empaquetado.
    """
    consulta_limpia = limpiar_entrada(pregunta_usuario)
    if consulta_limpia.startswith("🚫"):
        logger.warning(
            "Prompt injection blocked before routing. chat_id=%s trace=security_guard",
            chat_id,
        )
        yield consulta_limpia
        return

    clasificacion = clasificar_intencion(consulta_limpia)

    if clasificacion == "NORMATIVA":
        yield from hacer_pregunta(consulta_limpia)
        return

    if clasificacion == "OPERACIONAL":
        yield _mensaje_operacional_en_desarrollo()
        return

    if clasificacion == "SEGURIDAD":
        yield consulta_limpia
        return

    logger.warning(
        "LLM classification fallback triggered. state=AMBIGUO trace=[ERR_LLM_CLASS_TIMEOUT] user_input_len=%s chat_id=%s",
        len(consulta_limpia),
        chat_id,
    )
    yield _mensaje_ambiguedad()
    return
