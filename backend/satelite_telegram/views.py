"""Webhooks del satélite Telegram con trazabilidad y respuesta inmediata."""

import json
import re
import uuid

import redis
import requests
from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from seguridad.ofuscador import enmascarar_datos_sensibles
from .tasks import procesar_mensaje_ia

redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=1, decode_responses=True)
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
    """Busca coincidencias exactas en la memoria RAM (Redis) de las últimas 2 horas."""
    llave_cache = f"cache_q:{texto.lower().strip()}"
    return redis_client.get(llave_cache)


@csrf_exempt
def telegram_webhook(request):
    """Punto de entrada principal para la API de Telegram."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido. Utilice POST.'}, status=405)

    secret_token = request.META.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN')
    if secret_token != settings.TELEGRAM_SECRET_TOKEN:
        return HttpResponseForbidden('Forbidden')

    try:
        update = json.loads(request.body)
        request_id = str(uuid.uuid4())

        if 'message' not in update or 'text' not in update['message']:
            return JsonResponse({'status': 'ok', 'request_id': request_id})

        chat_id = update['message']['chat']['id']
        texto_usuario = update['message']['text']
        texto_usuario_sanitizado = enmascarar_datos_sensibles(texto_usuario)

        # Registro seguro de la trazabilidad de entrada del webhook.
        if texto_usuario_sanitizado:
            print(f"[TRACE] request_id={request_id} chat_id={chat_id} pregunta={texto_usuario_sanitizado}")

        respuesta_rapida = evaluar_intencion_basica(texto_usuario)
        if respuesta_rapida:
            enviar_mensaje_telegram(chat_id, respuesta_rapida)
            return JsonResponse({'status': 'ok', 'request_id': request_id})

        respuesta_cache = verificar_cache_volatil(texto_usuario)
        if respuesta_cache:
            mensaje_reciclado = f"⚡ [Respuesta desde Caché]\n\n{respuesta_cache}"
            enviar_mensaje_telegram(chat_id, mensaje_reciclado)
            return JsonResponse({'status': 'ok', 'request_id': request_id})

        procesar_mensaje_ia.delay(chat_id, texto_usuario, request_id)
        return JsonResponse({'status': 'ok', 'request_id': request_id})

    except Exception as exc:
        print(f"[ERROR] Fallo en telegram_webhook: {str(exc)}")
        return JsonResponse({'error': str(exc)}, status=500)


def enviar_mensaje_telegram(chat_id, texto):
    """Envío simple de mensajes a Telegram."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={'chat_id': chat_id, 'text': texto}, timeout=(5, 30))


def enviar_accion_escribiendo(chat_id):
    """Indica que el bot está redactando una respuesta."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendChatAction"
    requests.post(url, json={'chat_id': chat_id, 'action': 'typing'}, timeout=(5, 30))
