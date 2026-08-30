import json
import logging
import time
import uuid

import redis
import requests
from django.conf import settings
from qdrant_client import QdrantClient

from seguridad.ofuscador import enmascarar_datos_sensibles
from .breaker import GestorCircuitBreaker, CircuitOpenException
from .sanitizador import PromptInjectionException, validar_prompt_seguro

logger = logging.getLogger("planeta.rag_engine")

redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=1,
    decode_responses=True,
)
breaker = GestorCircuitBreaker(redis_client, key_prefix="rag", ttl_segundos=30, max_fallos=3)

OLLAMA_CHAT_URL = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
OLLAMA_EMBEDDINGS_URL = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/embeddings"
QDRANT_HOST = settings.QDRANT_HOST
QDRANT_PORT = settings.QDRANT_PORT
COLECCION = settings.QDRANT_COLLECTION

_RERANKER = None
_SPARSE_EMBEDDER = None


def verificar_salud_servicios(request_id=None, chat_id=None):
    """Valida que Qdrant y Ollama respondan antes de ejecutar la búsqueda."""
    endpoints = {
        "qdrant": f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}/",
        "ollama": f"{settings.OLLAMA_BASE_URL.rstrip('/')}/",
    }
    qdrant_ok = True
    ollama_ok = True

    for nombre, url in endpoints.items():
        inicio = time.perf_counter()
        try:
            respuesta = requests.get(url, timeout=2.0)
            ms = int((time.perf_counter() - inicio) * 1000)
            if respuesta.status_code != 200:
                logger.error(
                    "Dependencia no saludable. request_id=%s chat_id=%s servicio=%s status=%s endpoint=%s",
                    request_id,
                    chat_id,
                    nombre,
                    respuesta.status_code,
                    url,
                )
                if nombre == "qdrant":
                    qdrant_ok = False
                else:
                    ollama_ok = False
        except (requests.Timeout, requests.ConnectionError) as exc:
            ms = int((time.perf_counter() - inicio) * 1000)
            logger.error(
                "Timeout/conexión fallida. request_id=%s chat_id=%s servicio=%s endpoint=%s error=%s",
                request_id,
                chat_id,
                nombre,
                url,
                str(exc),
            )
            if nombre == "qdrant":
                qdrant_ok = False
            else:
                ollama_ok = False
        except Exception as exc:
            logger.error(
                "Fallo inesperado al verificar salud. request_id=%s chat_id=%s servicio=%s endpoint=%s error=%s",
                request_id,
                chat_id,
                nombre,
                url,
                str(exc),
            )
            if nombre == "qdrant":
                qdrant_ok = False
            else:
                ollama_ok = False

    if not qdrant_ok:
        breaker.registrar_fallo("qdrant")
    else:
        breaker.registrar_exito("qdrant")

    if not ollama_ok:
        breaker.registrar_fallo("ollama")
    else:
        breaker.registrar_exito("ollama")

    return qdrant_ok and ollama_ok


def obtener_reranker():
    """Carga un Cross-Encoder ligero para re-rankear candidatos por relevancia real."""
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER

    try:
        from sentence_transformers import CrossEncoder

        _RERANKER = CrossEncoder(
            "cross-encoder/ms-marco-MiniLM-L-6-v2",
            max_length=512,
            device="cpu",
        )
        return _RERANKER
    except Exception as exc:
        logger.warning("Cross-Encoder no disponible. error=%s", str(exc))
        return None


def obtener_sparse_embedder():
    """Carga un embedding sparse BM25 si está habilitado en la instalación."""
    global _SPARSE_EMBEDDER
    if _SPARSE_EMBEDDER is not None:
        return _SPARSE_EMBEDDER

    try:
        from fastembed import SparseEmbedding
    except ImportError:
        return None

    _SPARSE_EMBEDDER = SparseEmbedding(model_name="Qdrant/bm25")
    return _SPARSE_EMBEDDER


def generar_sparse_embedding(texto, sparse_embedder=None):
    """Genera un embedding sparse para búsqueda híbrida si FastEmbed está instalado."""
    if not texto:
        return None
    sparse_embedder = sparse_embedder or obtener_sparse_embedder()
    if sparse_embedder is None:
        return None

    try:
        embedding = next(sparse_embedder.embed([texto]))
    except Exception:
        return None

    if isinstance(embedding, dict):
        indices = list(embedding.get("indices", []))
        values = list(embedding.get("values", []))
    else:
        indices = list(getattr(embedding, "indices", []))
        values = list(getattr(embedding, "values", []))

    if not indices or not values:
        return None
    return {"indices": indices, "values": values}


def rerankear_fragmentos(pregunta_usuario, candidatos, request_id=None, chat_id=None):
    """Reordena 10 candidatos usando Cross-Encoder y devuelve el Top-3."""
    if not candidatos:
        return []

    reranker = obtener_reranker()
    if reranker is None:
        logger.warning(
            "Cross-Encoder no disponible; fallback a Top-3 sin re-ranking. request_id=%s chat_id=%s candidatos=%s",
            request_id,
            chat_id,
            len(candidatos),
        )
        return candidatos[:3]

    pares = [(pregunta_usuario, texto) for texto in candidatos]
    scores = reranker.predict(pares)
    ranked = sorted(zip(candidatos, scores), key=lambda item: float(item[1]), reverse=True)
    return [texto for texto, _ in ranked[:3]]


def _obtener_embedding_ollama(texto, request_id=None, chat_id=None):
    """Embedding denso para la pregunta usando Ollama y su modelo configurado."""
    payload = {"model": settings.OLLAMA_EMBEDDINGS_MODEL, "prompt": texto}
    try:
        respuesta = requests.post(OLLAMA_EMBEDDINGS_URL, json=payload, timeout=(5, 30))
        respuesta.raise_for_status()
        data = respuesta.json()
        embedding = data.get("embedding")
        if not isinstance(embedding, list):
            logger.error(
                "Embedding de Ollama inválido. request_id=%s chat_id=%s payload_keys=%s",
                request_id,
                chat_id,
                sorted(data.keys()),
            )
            return None
        return embedding
    except requests.exceptions.RequestException as exc:
        logger.error(
            "Fallo al pedir embedding denso a Ollama. request_id=%s chat_id=%s error=%s",
            request_id,
            chat_id,
            str(exc),
        )
        return None


def hacer_pregunta(pregunta_usuario, chat_id="-", request_id=None):
    """Busca en Qdrant, re-rankea y genera respuesta en streaming, siempre como generador."""
    if request_id is None:
        request_id = str(uuid.uuid4())

    pregunta_segura = enmascarar_datos_sensibles(pregunta_usuario)
    logger.info(
        "Consulta recibida para RAG. request_id=%s chat_id=%s len_query=%s",
        request_id,
        chat_id,
        len(str(pregunta_usuario)),
    )

    try:
        validar_prompt_seguro(pregunta_usuario)
    except PromptInjectionException as exc:
        logger.error(
            "Prompt injection detectado. request_id=%s chat_id=%s motivo=%s",
            request_id,
            chat_id,
            str(exc),
        )
        yield "Consulta bloqueada por seguridad: el contenido no es válido para este motor de inferencia."
        return

    try:
        breaker.allow_request("qdrant")
        breaker.allow_request("ollama")
    except CircuitOpenException as exc:
        logger.error(
            "Circuit breaker abierto. request_id=%s chat_id=%s servicio=%s",
            request_id,
            chat_id,
            str(exc),
        )
        yield "Servicio de búsqueda temporalmente inactivo. Intente nuevamente en unos minutos."
        return

    if not verificar_salud_servicios(request_id=request_id, chat_id=chat_id):
        logger.warning(
            "Busqueda abortada por salud de dependencias. request_id=%s chat_id=%s",
            request_id,
            chat_id,
        )
        yield "Servicio de búsqueda temporalmente inactivo."
        return

    embedding = _obtener_embedding_ollama(pregunta_segura, request_id=request_id, chat_id=chat_id)
    if embedding is None:
        logger.error(
            "No se pudo obtener embedding del usuario. request_id=%s chat_id=%s",
            request_id,
            chat_id,
        )
        yield "Servicio de inferencia temporalmente inactivo."
        return

    sparse_query = generar_sparse_embedding(pregunta_segura)
    cliente = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    try:
        consulta = cliente.query_points(
            collection_name=COLECCION,
            prefetch=[
                {
                    "query": {
                        "nearest": {
                            "vector": embedding,
                            "limit": 10,
                            "using": "dense",
                        }
                    }
                },
            ],
            query={"fusion": {"rrf": {"k": 60}}},
            limit=10,
            with_payload=True,
        )
    except Exception as exc:
        breaker.registrar_fallo("qdrant")
        logger.error(
            "Query Qdrant falló. request_id=%s chat_id=%s error=%s",
            request_id,
            chat_id,
            str(exc),
        )
        yield "Servicio de búsqueda temporalmente inactivo."
        return

    puntos = getattr(consulta, "points", None) or []
    candidatos = []
    for hit in puntos:
        payload = getattr(hit, "payload", None) or {}
        texto = payload.get("texto") or payload.get("content") or ""
        if texto.strip():
            candidatos.append(texto.strip())

    if not candidatos:
        logger.warning(
            "No se encontraron fragmentos útiles. request_id=%s chat_id=%s",
            request_id,
            chat_id,
        )
        yield "No encontré fragmentos útiles para responder esta consulta."
        return

    candidatos_top10 = candidatos[:10]
    fragmentos_top3 = rerankear_fragmentos(pregunta_segura, candidatos_top10, request_id=request_id, chat_id=chat_id)
    contexto = "\n\n".join(fragmentos_top3)

    logger.info(
        "Contexto final re-rankeado. request_id=%s chat_id=%s top3=%s",
        request_id,
        chat_id,
        len(fragmentos_top3),
    )

    prompt_experto = f"""
    Eres un especialista en normativas de servicios de agua potable.
    Contesta solo con base en el contexto oficial entregado.
    Si no lo encuentras, responde exactamente: "Lo siento, no encuentro información sobre esto en las normativas actuales registradas."

    Contexto:
    {contexto}

    Pregunta del usuario: {pregunta_segura}
    Respuesta:
    """

    payload = {
        "model": settings.MODELO_CLASIFICACION,
        "prompt": prompt_experto,
        "stream": True,
        "options": {
            "num_ctx": 2048,
            "temperature": 0.1,
            "num_predict": 400,
        },
    }

    try:
        respuesta = requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=(5, 30))
        respuesta.raise_for_status()

        for linea in respuesta.iter_lines(decode_unicode=True):
            if not linea:
                continue
            linea = linea.strip()
            if not linea:
                continue
            if linea.startswith("data:"):
                linea = linea[5:].strip()
            if not linea:
                continue
            try:
                data = json.loads(linea)
            except json.JSONDecodeError:
                continue
            token = data.get("response", "")
            if token:
                yield token
    except requests.exceptions.RequestException as exc:
        breaker.registrar_fallo("ollama")
        logger.error(
            "Streaming de Ollama falló. request_id=%s chat_id=%s error=%s",
            request_id,
            chat_id,
            str(exc),
        )
        yield "Servicio de inferencia temporalmente inactivo."
    except Exception as exc:
        breaker.registrar_fallo("ollama")
        logger.error(
            "Error no recuperable en streaming Ollama. request_id=%s chat_id=%s error=%s",
            request_id,
            chat_id,
            str(exc),
        )
        yield "Servicio de inferencia temporalmente inactivo."

