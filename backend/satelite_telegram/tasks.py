"""Módulo de Tareas Asíncronas (Celery) para el Satélite Telegram.

Gestiona las tareas pesadas de inferencia de IA en segundo plano.
Implementa escritura en Caché Volátil (Redis) para reciclar respuestas.
Además, controla el Satélite Nocturno para la vectorización diferida de PDFs.
"""

import logging
import time
import uuid

import requests
import redis
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone
from rag_engine.extractor import vectorizar_documento
from rag_engine.orquestador import procesar_consulta_orquestada
from seguridad.ofuscador import enmascarar_datos_sensibles
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from .models import DocumentoPendiente

logger = logging.getLogger("planeta.telegram")

# Conexión al Broker de Redis (Base de datos 1)
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=1,
    decode_responses=True,
)

# Tiempo de vida del caché en segundos (2 horas)
TIEMPO_EXPIRACION_CACHE = 7200


def registrar_consulta_sanitizada(chat_id, texto_usuario, respuesta_ia=None, request_id=None):
    """Guarda en RegistroConsulta texto anónimo del usuario y respuesta IA, si existe el modelo."""
    texto_seguro = enmascarar_datos_sensibles(texto_usuario or "")
    respuesta_segura = enmascarar_datos_sensibles(respuesta_ia or "")
    try:
        from satelite_telegram.models import RegistroConsulta
    except ImportError:
        return texto_seguro

    if RegistroConsulta is None:
        return texto_seguro

    try:
        campos = [field.name for field in RegistroConsulta._meta.get_fields()]
        kwargs = {}
        for campo in ['chat_id', 'usuario_id', 'usuario', 'consulta', 'texto', 'mensaje', 'texto_usuario', 'texto_ingresado', 'pregunta']:
            if campo in campos:
                kwargs[campo] = texto_seguro
                break
        for campo in ['respuesta', 'respuesta_ia', 'respuestaIA', 'resultado', 'contenido', 'texto_respuesta']:
            if campo in campos:
                kwargs[campo] = respuesta_segura
                break
        if not kwargs:
            return texto_seguro
        if 'chat_id' in campos and chat_id is not None:
            kwargs.setdefault('chat_id', chat_id)
        if request_id is not None and 'request_id' in campos:
            kwargs['request_id'] = request_id
        RegistroConsulta.objects.create(**kwargs)
    except Exception as exc:  # pragma: no cover - fall-back defensivo
        logger.error(
            "No se pudo persistir la consulta anonimizada. request_id=%s chat_id=%s error=%s",
            request_id,
            chat_id,
            str(exc),
        )
    return texto_seguro


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=10),
    reraise=True,
)
def enviar_peticion_telegram(payload, endpoint):
    """Envía una petición a Telegram con reintentos y backoff exponencial."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{endpoint}"
    respuesta = requests.post(url, json=payload, timeout=(5, 30))
    if respuesta.status_code == 429:
        raise requests.exceptions.HTTPError("Telegram rate limit: 429 Too Many Requests")
    respuesta.raise_for_status()
    return respuesta


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=10),
    reraise=True,
)
def enviar_mensaje_final(chat_id, texto):
    """Fallback final con sendMessage y reintentos exponenciales."""
    return enviar_peticion_telegram({'chat_id': chat_id, 'text': texto}, 'sendMessage')


@shared_task(bind=True)
def procesar_mensaje_ia(self, chat_id, texto_usuario, request_id=None):
    """Procesa consultas con streaming seguro y fallback a sendMessage si Telegram falla."""
    request_id = request_id or str(uuid.uuid4())
    texto_seguro = enmascarar_datos_sensibles(texto_usuario)
    texto_guardado = registrar_consulta_sanitizada(chat_id, texto_seguro, request_id=request_id)
    message_id = None
    streaming_activo = True
    buffer = ""
    respuesta_final = ""
    lock_key = f'lock_chat_{chat_id}'

    try:
        with redis_client.lock(lock_key, timeout=45, blocking_timeout=5):
            logger.info(
                "Procesando consulta RAG. request_id=%s chat_id=%s texto=%s",
                request_id,
                chat_id,
                texto_seguro,
            )
            try:
                respuesta_inicial = enviar_peticion_telegram(
                    {'chat_id': chat_id, 'text': 'Buscando en normativas...'},
                    'sendMessage',
                )
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "Telegram sendMessage inicial falló. request_id=%s chat_id=%s error=%s streaming_activo=False",
                    request_id,
                    chat_id,
                    str(exc),
                )
                streaming_activo = False
                respuesta_inicial = None

            if streaming_activo and respuesta_inicial is not None:
                if respuesta_inicial.status_code != 200:
                    logger.warning(
                        "Telegram initial send returned status %s. request_id=%s chat_id=%s streaming_activo=False",
                        getattr(respuesta_inicial, 'status_code', 'N/A'),
                        request_id,
                        chat_id,
                    )
                    streaming_activo = False
                else:
                    try:
                        payload = respuesta_inicial.json()
                        result = payload.get('result', {}) if isinstance(payload, dict) else {}
                        message_id = result.get('message_id')
                        if message_id is None:
                            logger.warning(
                                "Telegram initial send missing message_id. request_id=%s chat_id=%s streaming_activo=False",
                                request_id,
                                chat_id,
                            )
                            streaming_activo = False
                    except (ValueError, TypeError, AttributeError, KeyError) as exc:
                        logger.warning(
                            "Telegram initial payload invalid. request_id=%s chat_id=%s error=%s streaming_activo=False",
                            request_id,
                            chat_id,
                            str(exc),
                        )
                        streaming_activo = False

            for token in procesar_consulta_orquestada(texto_seguro, chat_id):
                if not token:
                    continue
                buffer += str(token)

                if streaming_activo and message_id is not None:
                    try:
                        enviar_peticion_telegram(
                            {'chat_id': chat_id, 'message_id': message_id, 'text': buffer},
                            'editMessageText',
                        )
                    except requests.exceptions.RequestException as exc:
                        logger.warning(
                            "editMessageText falló; se desactiva streaming. request_id=%s chat_id=%s error=%s",
                            request_id,
                            chat_id,
                            str(exc),
                        )
                        streaming_activo = False
                        message_id = None

            respuesta_final = buffer.strip() or 'No pude generar una respuesta válida.'
            respuesta_final_segura = enmascarar_datos_sensibles(respuesta_final)
            registrar_consulta_sanitizada(chat_id, texto_seguro, respuesta_ia=respuesta_final_segura, request_id=request_id)

            if streaming_activo and message_id is not None:
                try:
                    enviar_peticion_telegram(
                        {'chat_id': chat_id, 'message_id': message_id, 'text': respuesta_final_segura},
                        'editMessageText',
                    )
                except requests.exceptions.RequestException as exc:
                    logger.warning(
                        "Fallo al editar el mensaje final. request_id=%s chat_id=%s error=%s fallback=sendMessage",
                        request_id,
                        chat_id,
                        str(exc),
                    )
                    streaming_activo = False

            if not streaming_activo:
                try:
                    enviar_mensaje_final(chat_id, respuesta_final_segura)
                except requests.exceptions.RequestException as exc:
                    logger.error(
                        "Fallback final sendMessage falló. request_id=%s chat_id=%s error=%s",
                        request_id,
                        chat_id,
                        str(exc),
                    )

            redis_client.setex(f"cache_q:{texto_seguro.lower().strip()}", TIEMPO_EXPIRACION_CACHE, respuesta_final_segura)

    except SoftTimeLimitExceeded:
        respuesta_final = 'El servidor de IA está saturado en este momento. Intente en unos minutos.'
        logger.warning(
            "SoftTimeLimitExceeded. request_id=%s chat_id=%s query=%s timeout_warning=%s",
            request_id,
            chat_id,
            texto_seguro,
            respuesta_final,
        )
        try:
            enviar_mensaje_final(chat_id, enmascarar_datos_sensibles(respuesta_final))
        except requests.exceptions.RequestException as exc:
            logger.error(
                "No se pudo enviar el aviso de timeout a Telegram. request_id=%s chat_id=%s error=%s",
                request_id,
                chat_id,
                str(exc),
            )
        return

    except Exception as exc:
        logger.error(
            "Falló la tarea de IA. request_id=%s chat_id=%s error=%s",
            request_id,
            chat_id,
            str(exc),
        )
        return


@shared_task
def procesar_documentos_pendientes():
    """
    Satélite Nocturno: Tarea programada (Cron Job) que busca documentos PDF 
    en estado 'PENDIENTE', los vectoriza en Qdrant y actualiza su estado.
    """
    documentos = DocumentoPendiente.objects.filter(estado='PENDIENTE')
    
    if not documentos.exists():
        return "Operación cancelada: No hay documentos pendientes en la base de datos."
        
    for doc in documentos:
        try:
            doc.estado = 'PROCESANDO'
            doc.save()
            
            ruta_pdf = doc.archivo.path
            logger.info(
               "Night satellite ingest started. archivo=%s",
               doc.nombre_archivo,
               extra={'chat_id': '-', 'tiempo_ms': 0},
            )
             
            # --- CONEXIÓN AL MOTOR DE INGESTA MASIVA ---
            vectores_creados = vectorizar_documento(ruta_pdf, doc.nombre_archivo)
            logger.info(
                "Night satellite ingest completed. archivo=%s fragmentos=%s",
                doc.nombre_archivo,
                vectores_creados,
                extra={'chat_id': '-', 'tiempo_ms': 0},
            )
            # -------------------------------------------
            
            doc.estado = 'COMPLETADO'
            doc.fecha_procesamiento = timezone.now()
            doc.save()
            
        except Exception as e:
            doc.estado = 'ERROR'
            doc.save()
            logger.error(
                "Night satellite ingest failed. archivo=%s error=%s",
                doc.nombre_archivo,
                str(e),
                extra={'chat_id': '-', 'tiempo_ms': 0},
            )
            
    return f"Ciclo de ingesta finalizado. {documentos.count()} documentos intentados."