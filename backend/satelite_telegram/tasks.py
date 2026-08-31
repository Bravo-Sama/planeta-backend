"""Módulo de Tareas Asíncronas (Celery) para el Satélite Telegram.

Gestiona las tareas pesadas de inferencia de IA en segundo plano.
Implementa idempotencia estricta, tolerancia a fallos, streaming controlado
y patrón Write-Behind para desacoplar MariaDB del flujo del usuario.
"""

import json
import logging
import time
import uuid
import hashlib

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

TIEMPO_EXPIRACION_CACHE = 7200


def registrar_consulta_sanitizada(chat_id, texto_usuario, respuesta_ia=None, request_id=None):
    """
    Patrón Write-Behind: No toca MariaDB en tiempo real. 
    Empuja el registro a una cola de Redis en O(1) milisegundos.
    """
    texto_seguro = enmascarar_datos_sensibles(texto_usuario or "")
    respuesta_segura = enmascarar_datos_sensibles(respuesta_ia or "")
    
    payload = {
        "chat_id": chat_id,
        "texto_usuario": texto_seguro,
        "respuesta_ia": respuesta_segura,
        "request_id": request_id,
        "timestamp": time.time()
    }
    
    try:
        # Lpush encola el log en la lista "cola_logs_mariadb" de Redis
        redis_client.lpush("cola_logs_mariadb", json.dumps(payload))
    except Exception as exc:
        logger.error(f"[{request_id}] Fallo crítico en Redis al encolar log: {str(exc)}")
        
    return texto_seguro


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
def enviar_peticion_telegram(payload, endpoint):
    """Envía una petición a Telegram con reintentos y backoff exponencial."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{endpoint}"
    respuesta = requests.post(url, json=payload, timeout=(5, 30))
    if respuesta.status_code == 429:
        raise requests.exceptions.HTTPError("Telegram rate limit: 429 Too Many Requests")
    respuesta.raise_for_status()
    return respuesta


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
def enviar_mensaje_final(chat_id, texto):
    """Fallback final garantizado."""
    return enviar_peticion_telegram({'chat_id': chat_id, 'text': texto}, 'sendMessage')


@shared_task(bind=True, soft_time_limit=45, max_retries=3)
def procesar_mensaje_ia(self, chat_id, texto_usuario, request_id=None):
    """Tarea inmortal: Tolerancia a fallos, idempotencia y streaming seguro."""
    request_id = request_id or str(uuid.uuid4())
    texto_seguro = enmascarar_datos_sensibles(texto_usuario)
    
    # 1. Deduplicación Estricta (Idempotencia)
    hash_consulta = hashlib.md5(f"{chat_id}:{texto_seguro}".encode('utf-8')).hexdigest()
    key_idempotencia = f"consulta:estado:{hash_consulta}"
    
    if redis_client.exists(key_idempotencia):
        logger.warning(f"[{request_id}] Consulta duplicada detectada y bloqueada en red ({hash_consulta}).")
        return "Duplicado descartado"

    redis_client.setex(key_idempotencia, 60, "procesando")
    
    # Variables de estado controladas
    message_id = None
    streaming_activo = True
    buffer = ""
    respuesta_final = ""
    lock_key = f'lock_chat_{chat_id}'
    caracteres_desde_ultima_edicion = 0

    try:
        # Aislamos MariaDB (Write-behind asíncrono)
        registrar_consulta_sanitizada(chat_id, texto_seguro, request_id=request_id)
        
        with redis_client.lock(lock_key, timeout=45, blocking_timeout=5):
            # 2. Envío de Placeholder
            try:
                resp_inicial = enviar_peticion_telegram({'chat_id': chat_id, 'text': 'Buscando en normativas...'}, 'sendMessage')
                message_id = resp_inicial.json().get('result', {}).get('message_id')
                if not message_id:
                    streaming_activo = False
            except Exception as exc:
                logger.warning(f"[{request_id}] Fallo inicial Telegram: {str(exc)}")
                streaming_activo = False

            # 3. Flujo RAG con Streaming Protegido
            for token in procesar_consulta_orquestada(texto_seguro, chat_id):
                if not token:
                    continue
                buffer += str(token)
                caracteres_desde_ultima_edicion += len(str(token))

                # Throttle API Telegram: Editamos máximo cada 150 caracteres
                if streaming_activo and message_id and caracteres_desde_ultima_edicion >= 150:
                    try:
                        enviar_peticion_telegram({'chat_id': chat_id, 'message_id': message_id, 'text': buffer}, 'editMessageText')
                        caracteres_desde_ultima_edicion = 0
                    except Exception:
                        streaming_activo = False # Si falla la edición, apagamos el streaming para no banearnos

            respuesta_final = buffer.strip() or "No pude generar una respuesta válida."

    except redis.exceptions.LockError:
        respuesta_final = "Por favor, espera a que termine de responder tu consulta anterior."
        streaming_activo = False
        
    except SoftTimeLimitExceeded:
        respuesta_final = "El sistema de IA está procesando demasiadas consultas. Intenta en unos minutos."
        streaming_activo = False
        logger.error(f"[{request_id}] SoftTimeLimitExceeded alcanzado.")
        
    except Exception as exc:
        respuesta_final = "El motor de inteligencia artificial se encuentra en modo degradado."
        streaming_activo = False
        logger.critical(f"[{request_id}] Fallo crítico en el flujo RAG: {str(exc)}", exc_info=True)

    finally:
        # 4. Bloque Inquebrantable de Cierre
        respuesta_final_segura = enmascarar_datos_sensibles(respuesta_final)
        
        # Guardado del historial (Write-behind asíncrono)
        registrar_consulta_sanitizada(chat_id, texto_seguro, respuesta_ia=respuesta_final_segura, request_id=request_id)
        
        # Entrega garantizada a Telegram
        if streaming_activo and message_id:
            try:
                enviar_peticion_telegram({'chat_id': chat_id, 'message_id': message_id, 'text': respuesta_final_segura}, 'editMessageText')
            except Exception:
                enviar_mensaje_final(chat_id, respuesta_final_segura)
        else:
            enviar_mensaje_final(chat_id, respuesta_final_segura)

        # Limpieza de estados
        redis_client.setex(f"cache_q:{texto_seguro.lower().strip()}", TIEMPO_EXPIRACION_CACHE, respuesta_final_segura)
        redis_client.delete(key_idempotencia)
        
    return "Procesamiento completado con escudo activo"


@shared_task
def procesar_documentos_pendientes():
    """Satélite Nocturno: Vectorización diferida de PDFs."""
    documentos = DocumentoPendiente.objects.filter(estado='PENDIENTE')
    if not documentos.exists():
        return "Operación cancelada: No hay documentos pendientes."
        
    for doc in documentos:
        try:
            doc.estado = 'PROCESANDO'
            doc.save()
            
            logger.info(f"Iniciando vectorización masiva: {doc.nombre_archivo}")
            vectores_creados = vectorizar_documento(doc.archivo.path, doc.nombre_archivo)
            
            doc.estado = 'COMPLETADO'
            doc.fecha_procesamiento = timezone.now()
            doc.save()
        except Exception as e:
            doc.estado = 'ERROR'
            doc.save()
            logger.error(f"Fallo en ingesta nocturna de {doc.nombre_archivo}: {str(e)}")
            
    return f"Ciclo de ingesta finalizado. {documentos.count()} procesados."


@shared_task
def sincronizar_registros_mariadb():
    """
    Tarea programada (Beat) que saca los logs de Redis y los inserta 
    en bloque en MariaDB. Si MariaDB falla, los devuelve a Redis.
    """
    lote_maximo = 50
    logs_raw = []
    
    # Extraemos hasta 50 registros de la cola
    for _ in range(lote_maximo):
        item = redis_client.rpop("cola_logs_mariadb")
        if item:
            logs_raw.append(item)
        else:
            break
            
    if not logs_raw:
        return "0 logs pendientes para MariaDB."
        
    try:
        from satelite_telegram.models import RegistroConsulta
        campos = [field.name for field in RegistroConsulta._meta.get_fields()]
        
        nuevos_registros = []
        for raw in logs_raw:
            try:
                datos = json.loads(raw)
            except Exception:
                continue
                
            kwargs = {}
            if 'request_id' in campos: kwargs['request_id'] = datos.get('request_id')
            if 'chat_id' in campos: kwargs['chat_id'] = datos.get('chat_id')
            
            # Mapeo dinámico de tu modelo
            for c in ['consulta', 'texto', 'mensaje', 'texto_usuario', 'pregunta']:
                if c in campos:
                    kwargs[c] = datos.get('texto_usuario')
                    break
            for c in ['respuesta', 'respuesta_ia', 'respuestaIA', 'resultado', 'texto_respuesta']:
                if c in campos:
                    kwargs[c] = datos.get('respuesta_ia')
                    break
                    
            nuevos_registros.append(RegistroConsulta(**kwargs))
            
        # Bulk Create: 1 sola transacción a disco duro en vez de 50
        if nuevos_registros:
            RegistroConsulta.objects.bulk_create(nuevos_registros)
            logger.info(f"Write-Behind exitoso: {len(nuevos_registros)} registros volcados a MariaDB.")
            
        return f"Volcados {len(nuevos_registros)} registros."
        
    except Exception as exc:
        logger.error(f"Fallo al volcar en MariaDB. Devolviendo a Redis. Error: {str(exc)}")
        # Si DB colapsa, devolvemos los datos a Redis para no perderlos
        for raw in logs_raw:
            redis_client.lpush("cola_logs_mariadb", raw)
        return "Fallo DB. Registros rescatados en Redis."