"""
Módulo de Tareas Asíncronas (Celery) para el Satélite Telegram.

Gestiona las tareas pesadas de inferencia de IA en segundo plano.
Implementa escritura en Caché Volátil (Redis) para reciclar respuestas.
Además, controla el Satélite Nocturno para la vectorización diferida de PDFs.
"""

import requests
import redis
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from rag_engine.buscador import hacer_pregunta 
from rag_engine.extractor import vectorizar_documento
from .models import DocumentoPendiente

# Conexión al Broker de Redis (Base de datos 1)
redis_client = redis.Redis(host='redis', port=6379, db=1, decode_responses=True)

# Tiempo de vida del caché en segundos (2 horas)
TIEMPO_EXPIRACION_CACHE = 7200


@shared_task
def procesar_mensaje_ia(chat_id, texto_usuario):
    """
    Procesa la consulta técnica utilizando el motor RAG (Llama 3 + Qdrant),
    almacena el resultado en el caché de Redis y lo envía a Telegram.
    """
    try:
        respuesta_ia = hacer_pregunta(texto_usuario)
        llave_cache = f"cache_q:{texto_usuario.lower().strip()}"
        redis_client.setex(llave_cache, TIEMPO_EXPIRACION_CACHE, respuesta_ia)
        
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={'chat_id': chat_id, 'text': respuesta_ia}, timeout=5)
        
    except Exception as e:
        print(f"[ERROR CELERY] Fallo al procesar IA para {chat_id}: {e}")


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
            print(f"[SATÉLITE NOCTURNO] Iniciando vectorización de: {doc.nombre_archivo}")
            
            # --- CONEXIÓN AL MOTOR DE INGESTA MASIVA ---
            vectores_creados = vectorizar_documento(ruta_pdf, doc.nombre_archivo)
            print(f"[SATÉLITE NOCTURNO] ✅ {doc.nombre_archivo} inyectado. {vectores_creados} fragmentos.")
            # -------------------------------------------
            
            doc.estado = 'COMPLETADO'
            doc.fecha_procesamiento = timezone.now()
            doc.save()
            
        except Exception as e:
            doc.estado = 'ERROR'
            doc.save()
            print(f"[ERROR SATÉLITE NOCTURNO] Fallo crítico en {doc.nombre_archivo}: {str(e)}")
            
    return f"Ciclo de ingesta finalizado. {documentos.count()} documentos intentados."