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

# Conexión Redis compartida
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=1,
    decode_responses=True,
)

# 1. Breakers independientes: Si falla Ollama, no castigamos a Qdrant y viceversa
breaker_qdrant = GestorCircuitBreaker(servicio="qdrant", umbral_fallos=3, ttl_abierto=30)
breaker_ollama = GestorCircuitBreaker(servicio="ollama", umbral_fallos=3, ttl_abierto=30)

OLLAMA_CHAT_URL = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
OLLAMA_EMBEDDINGS_URL = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/embeddings"
QDRANT_HOST = settings.QDRANT_HOST
QDRANT_PORT = settings.QDRANT_PORT
COLECCION = settings.QDRANT_COLLECTION

_RERANKER = None
_SPARSE_EMBEDDER = None


# --- FUNCIONES AUXILIARES (CACHÉ EN MEMORIA) ---

def obtener_reranker():
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER
    try:
        from sentence_transformers import CrossEncoder
        _RERANKER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", max_length=512, device="cpu")
        return _RERANKER
    except Exception as exc:
        logger.warning("Cross-Encoder no disponible. error=%s", str(exc))
        return None

def obtener_sparse_embedder():
    global _SPARSE_EMBEDDER
    if _SPARSE_EMBEDDER is not None:
        return _SPARSE_EMBEDDER
    try:
        from fastembed import SparseEmbedding
        _SPARSE_EMBEDDER = SparseEmbedding(model_name="Qdrant/bm25")
        return _SPARSE_EMBEDDER
    except ImportError:
        return None

def generar_sparse_embedding(texto, sparse_embedder=None):
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
    if not candidatos:
        return []
    reranker = obtener_reranker()
    if reranker is None:
        logger.warning(f"[{request_id}] Cross-Encoder no disponible; fallback a Top-3 base.")
        return candidatos[:3]

    pares = [(pregunta_usuario, texto) for texto in candidatos]
    scores = reranker.predict(pares)
    ranked = sorted(zip(candidatos, scores), key=lambda item: float(item[1]), reverse=True)
    return [texto for texto, _ in ranked[:3]]


def _obtener_embedding_ollama(texto, request_id=None, chat_id=None):
    try:
        breaker_ollama.allow_request(request_id)
        payload = {"model": settings.OLLAMA_EMBEDDINGS_MODEL, "prompt": texto}
        respuesta = requests.post(OLLAMA_EMBEDDINGS_URL, json=payload, timeout=(5, 30))
        respuesta.raise_for_status()
        breaker_ollama.registrar_exito(request_id)
        
        return respuesta.json().get("embedding")
    
    except CircuitOpenException:
        logger.warning(f"[{request_id}] Ollama embeddings aislado por el Breaker.")
        return None
    except Exception as exc:
        breaker_ollama.registrar_fallo(request_id)
        logger.error(f"[{request_id}] Fallo al pedir embedding denso: {str(exc)}")
        return None


# --- DESACOPLAMIENTO DE RESPONSABILIDADES (FASE 2) ---

def recuperar_contexto(pregunta_segura, request_id=None, chat_id=None):
    """Fase A: Busca en Qdrant y re-rankea. Aislada del LLM."""
    try:
        breaker_qdrant.allow_request(request_id)
        
        # 1. Obtener embeddings de la pregunta
        embedding = _obtener_embedding_ollama(pregunta_segura, request_id=request_id, chat_id=chat_id)
        if embedding is None:
            return [] # Sin embedding no podemos hacer búsqueda híbrida
            
        # 2. Búsqueda en Qdrant
        cliente = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=5.0)
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
        
        breaker_qdrant.registrar_exito(request_id)
        
        # 3. Extracción de candidatos
        puntos = getattr(consulta, "points", None) or []
        candidatos = [
            (getattr(hit, "payload", None) or {}).get("texto") or (getattr(hit, "payload", None) or {}).get("content") or ""
            for hit in puntos
        ]
        candidatos = [c.strip() for c in candidatos if c.strip()]
        
        # 4. Reranking estricto
        return rerankear_fragmentos(pregunta_segura, candidatos[:10], request_id=request_id, chat_id=chat_id)
        
    except CircuitOpenException:
        logger.warning(f"[{request_id}] Qdrant aislado por el Breaker.")
        return []
    except Exception as exc:
        breaker_qdrant.registrar_fallo(request_id)
        logger.error(f"[{request_id}] Fallo de red con Qdrant: {str(exc)}")
        return []


def generar_respuesta_llm(pregunta_segura, fragmentos_top3, request_id=None, chat_id=None):
    """Fase B: Streaming desde Ollama. Garantiza devolver generador pase lo que pase."""
    try:
        breaker_ollama.allow_request(request_id)
        
        contexto = "\n\n".join(fragmentos_top3) if fragmentos_top3 else "Sin información normativa registrada."
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
            "options": {"num_ctx": 2048, "temperature": 0.1, "num_predict": 400},
        }

        with requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=(5, 30)) as respuesta:
            respuesta.raise_for_status()
            breaker_ollama.registrar_exito(request_id)
            
            for linea in respuesta.iter_lines(decode_unicode=True):
                if not linea:
                    continue
                linea = linea.strip()
                if linea.startswith("data:"):
                    linea = linea[5:].strip()
                try:
                    data = json.loads(linea)
                    token = data.get("response", "")
                    if token:
                        yield token
                except json.JSONDecodeError:
                    continue
                    
    except CircuitOpenException:
        yield "El motor de inteligencia artificial está protegido por mantenimiento temporal. [ERR_LLM_OPEN]"
    except Exception as exc:
        breaker_ollama.registrar_fallo(request_id)
        logger.error(f"[{request_id}] Error en generación LLM: {str(exc)}")
        yield "El servicio de inferencia está experimentando intermitencias. [ERR_LLM_NET]"


def hacer_pregunta(pregunta_usuario, chat_id="-", request_id=None):
    """Orquestador inmutable: Evalúa seguridad, extrae contexto y genera respuesta."""
    request_id = request_id or str(uuid.uuid4())
    pregunta_segura = enmascarar_datos_sensibles(pregunta_usuario)
    logger.info(f"[{request_id}] RAG Iniciado chat_id={chat_id}")

    try:
        validar_prompt_seguro(pregunta_usuario)
    except PromptInjectionException as exc:
        logger.error(f"[{request_id}] Seguridad RAG: Prompt bloqueado - {str(exc)}")
        yield "Consulta bloqueada por seguridad. [ERR_SEC_01]"
        return

    # Extracción de contexto (Breaker de Qdrant actúa aquí)
    fragmentos = recuperar_contexto(pregunta_segura, request_id, chat_id)
    
    if not fragmentos:
        logger.warning(f"[{request_id}] RAG advierte falta de contexto. Generando respuesta con contexto vacío.")
    
    # Generación de respuesta (Breaker de Ollama actúa aquí)
    yield from generar_respuesta_llm(pregunta_segura, fragmentos, request_id, chat_id)