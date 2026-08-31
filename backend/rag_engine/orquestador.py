"""Orquestador principal de consultas de Planeta.

Mantiene un contrato de salida inmutable: todas las rutas devuelven un generador.
La decisión de consulta se envía a RAG o a datos operativos y nunca se adivina
el tipo de retorno del consumidor. Integra tolerancia a fallos en el enrutamiento.
"""

import logging
import uuid
import requests
import redis
from django.conf import settings

from .buscador import hacer_pregunta
from .breaker import GestorCircuitBreaker, CircuitOpenException
from .sanitizador import validar_prompt_seguro, PromptInjectionException

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
MODELO_CLASIFICACION = settings.MODELO_CLASIFICACION

# Conexión Redis compartida
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=1,
    decode_responses=True,
)

# Breaker específico para tareas de clasificación. Aisla el orquestador de las caídas de Ollama.
breaker_clasificador = GestorCircuitBreaker(servicio="clasificador", umbral_fallos=3, ttl_abierto=30)


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


def clasificar_intencion(pregunta_usuario, request_id="N/A"):
    """Clasifica la consulta en NORMATIVA, OPERACIONAL o AMBIGUO usando Llama 3."""
    try:
        # 1. Verificación del Breaker
        breaker_clasificador.allow_request(request_id)
        
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
        {pregunta_usuario}
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

        # 2. Petición al LLM
        respuesta = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=(2, 5))
        respuesta.raise_for_status()
        
        # 3. Éxito: Reseteamos el breaker
        breaker_clasificador.registrar_exito(request_id)
        
        # 4. Parseo de respuesta
        texto = respuesta.json().get("response", "").strip().upper()
        
        if any(keyword in texto for keyword in ["NORMATIVA", "OPERACIONAL"]):
            return "NORMATIVA" if "NORMATIVA" in texto else "OPERACIONAL"
            
        return "AMBIGUO"

    except CircuitOpenException:
        logger.warning(f"[{request_id}] LLM Clasificador Aislado por Breaker. Degradando a AMBIGUO.")
        return "AMBIGUO"
        
    except requests.exceptions.RequestException as exc:
        breaker_clasificador.registrar_fallo(request_id)
        logger.error(f"[{request_id}] Error de red LLM classification. error={str(exc)} trace=[ERR_LLM_CLASS_NET]")
        return "AMBIGUO"
        
    except Exception as exc:
        breaker_clasificador.registrar_fallo(request_id)
        logger.error(f"[{request_id}] Unexpected LLM classification failure. error={str(exc)} trace=[ERR_LLM_CLASS_INT]")
        return "AMBIGUO"


def procesar_consulta_orquestada(pregunta_usuario, chat_id, request_id=None):
    """Orquesta la consulta y siempre devuelve un generador.

    Esta función preserva un contrato inmutable para el consumidor: nunca emite un
    string plano fuera del flujo iterable. Si la ruta es RAG, usa `yield from`; si
    es operativa o ambigua, usa `yield` con el mensaje final ya empaquetado.
    """
    request_id = request_id or str(uuid.uuid4())
    
    try:
        # 1. Defensa Perimetral Anti-Inyección
        validar_prompt_seguro(pregunta_usuario)
        
        # 2. Clasificación (Silenciosa y a prueba de fallos)
        clasificacion = clasificar_intencion(pregunta_usuario, request_id)

        # 3. Enrutamiento Inmutable
        if clasificacion == "NORMATIVA":
            yield from hacer_pregunta(pregunta_usuario, chat_id, request_id)
            return

        if clasificacion == "OPERACIONAL":
            yield _mensaje_operacional_en_desarrollo()
            return

        yield _mensaje_ambiguedad()
        return

    except PromptInjectionException as exc:
        logger.warning(f"[{request_id}] Prompt injection blocked before routing. chat_id={chat_id} trace=security_guard")
        yield "La solicitud viola las políticas de seguridad del sistema y no puede ser procesada. [ERR_SEC_01]"
        return
        
    except Exception as exc:
        logger.critical(f"[{request_id}] Colapso absoluto en orquestador central: {str(exc)}", exc_info=True)
        yield "El núcleo del sistema experimenta intermitencias graves. Por favor, intenta en unos minutos. [ERR_ORQ_CRITICAL]"
        return