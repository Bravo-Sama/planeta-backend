"""
Módulo de Controladores (Views) para el Satélite Telegram.

Responsabilidades:
1. Recibir webhooks de Telegram.
2. Enrutar intenciones básicas (saludos/despedidas).
3. Interceptar consultas recurrentes mediante Caché Volátil (Redis).
4. Delegar consultas complejas al motor de filas asíncrono (Celery).
"""

import json
import re
import redis
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from .tasks import procesar_mensaje_ia

redis_client = redis.Redis(host='redis', port=6379, db=1, decode_responses=True)
TIEMPO_PROMEDIO_INFERENCIA_SEGUNDOS = 5  


def evaluar_intencion_basica(texto):
    """Evalúa expresiones regulares para respuestas de latencia cero."""
    texto_limpio = texto.lower().strip()
    
    if re.match(r'^(hola|buenos d[íi]as|buenas tardes|buenas noches|hey|saludos)\b', texto_limpio):
        return "¡Hola! Soy Planeta. ¿En qué te puedo ayudar con la documentación técnica hoy?"
    if re.match(r'^(gracias|muchas gracias|vale|excelente|perfecto)\b', texto_limpio):
        return "¡De nada! Quedo a tu disposición si necesitas consultar algo más."
    if re.match(r'^(adi[óo]s|chao|hasta luego|nos vemos|bye)\b', texto_limpio):
        return "¡Hasta pronto! Sesión de consultas finalizada."
    return None


def verificar_cache_volatil(texto):
    """
    Busca coincidencias exactas en la memoria RAM (Redis) de las últimas 2 horas.
    """
    llave_cache = f"cache_q:{texto.lower().strip()}"
    respuesta = redis_client.get(llave_cache)
    return respuesta


@csrf_exempt
def telegram_webhook(request):
    """Punto de entrada principal para la API de Telegram."""
    if request.method == 'POST':
        try:
            update = json.loads(request.body)
            
            if 'message' in update and 'text' in update['message']:
                chat_id = update['message']['chat']['id']
                texto_usuario = update['message']['text']
                
                # --- FASE 2.A: FILTRO DE INTENCIÓN BÁSICA ---
                respuesta_rapida = evaluar_intencion_basica(texto_usuario)
                if respuesta_rapida:
                    enviar_mensaje_telegram(chat_id, respuesta_rapida)
                    return JsonResponse({'status': 'ok'})

                # --- FASE 2.B: INTERCEPTOR DE CACHÉ VOLÁTIL ---
                respuesta_cache = verificar_cache_volatil(texto_usuario)
                if respuesta_cache:
                    mensaje_reciclado = f"⚡ [Respuesta desde Caché]\n\n{respuesta_cache}"
                    enviar_mensaje_telegram(chat_id, mensaje_reciclado)
                    return JsonResponse({'status': 'ok'})
                
                # --- FASE 1: GESTIÓN DE FILAS Y CARGA (CELERY) ---
                tareas_en_cola = redis_client.llen('celery')
                
                if tareas_en_cola > 0:
                    tiempo_espera = (tareas_en_cola + 1) * TIEMPO_PROMEDIO_INFERENCIA_SEGUNDOS
                    mensaje_estado = f"El sistema presenta demanda. Posición en fila: {tareas_en_cola + 1}. ETA: {tiempo_espera} segundos."
                    enviar_mensaje_telegram(chat_id, mensaje_estado)
                else:
                    enviar_accion_escribiendo(chat_id)
                
                procesar_mensaje_ia.delay(chat_id, texto_usuario)
                
            return JsonResponse({'status': 'ok'})
        
        except Exception as e:
            print(f"[ERROR] Fallo en telegram_webhook: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)
            
    return JsonResponse({'error': 'Método no permitido. Utilice POST.'}, status=405)


def enviar_mensaje_telegram(chat_id, texto):
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={'chat_id': chat_id, 'text': texto}, timeout=5)


def enviar_accion_escribiendo(chat_id):
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendChatAction"
    requests.post(url, json={'chat_id': chat_id, 'action': 'typing'}, timeout=5)