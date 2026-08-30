"""Módulo de extracción e ingesta de documentos para Aguas Décimas.

Este módulo limpia el texto extraído de PDFs, lo fragmenta usando un chunking
inteligente con solapamiento estricto y lo inserta en Qdrant con metadatos de
origen, número de bloque y timestamp de ingesta.

Además, habilita un índice híbrido en Qdrant con:
- vectores densos (Ollama / semánticos)
- vectores dispersos (BM25 / sparse) generados con FastEmbed
"""

import os
import re
import uuid
from datetime import datetime, timezone

import fitz  # PyMuPDF
import requests
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
COLECCION = os.getenv("QDRANT_COLLECTION", "aguas_decimas")
OLLAMA_URL = os.getenv(
    "OLLAMA_EMBEDDINGS_URL",
    "http://host.docker.internal:11434/api/embeddings",
)

_SPARSE_EMBEDDER = None


def limpiar_texto(texto):
    """Limpia encabezados, pies de página, índices y saltos redundantes."""
    if not texto:
        return ""

    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = texto.replace("\u00a0", " ")

    patrones_a_eliminar = [
        r"(?im)^\s*(?:PÁGINA|PAGINA)\s*[:#-]?\s*\d+\s*(?:DE|of)\s*\d+\s*$",
        r"(?im)^\s*(?:ÍNDICE|INDICE|CONTENIDO|TABLA DE CONTENIDO)\s*:??\s*$",
        r"(?im)^\s*(?:Aguas\s+Décimas|AGUAS\s+DÉCIMAS)\s*$",
        r"(?im)^\s*[-*_]{3,}\s*$",
        r"(?im)^\s*\d+\s*$",
        r"(?im)^\s*(?:SECCIÓN|SECCION|TÍTULO|TITULO|CAPÍTULO|CAPITULO)\s*[:\-]?\s*.*$",
    ]
    for patron in patrones_a_eliminar:
        texto = re.sub(patron, "", texto)

    texto = re.sub(r"(?im)^\s*(?:Aguas\s+Décimas|AGUAS\s+DÉCIMAS)\s*[-–—:]\s*.*$", "", texto)
    texto = re.sub(r"(?im)^\s*(?:NORMA|NORMATIVA|RESOLUCIÓN|RESOLUCION)\s*[:\-].*$", "", texto)
    texto = re.sub(r"(?im)^\s*\d+[\.)]\s+", "", texto)
    texto = re.sub(r"(?im)^\s*[A-ZÁÉÍÓÚÜÑ]{1,3}\s*$", "", texto)

    texto = re.sub(r"[ \t]+\n", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    texto = re.sub(r"\s{2,}", " ", texto)
    texto = re.sub(r"\n\s+", "\n", texto)
    texto = re.sub(r"(?<=[a-záéíóúüñ])\n(?=[a-záéíóúüñ])", " ", texto)

    return texto.strip()


clean_text = limpiar_texto
clean_text_with_regex = limpiar_texto


def extraer_texto_pdf(ruta_pdf):
    """Extrae el texto de un PDF y limpia el contenido antes de fragmentar."""
    try:
        with fitz.open(ruta_pdf) as documento:
            texto = "".join(pagina.get_text("text") for pagina in documento)
        return limpiar_texto(texto)
    except Exception as exc:
        raise RuntimeError(f"Error crítico al leer el PDF {ruta_pdf}: {str(exc)}")


def obtener_embedding(texto):
    """Solicita la vectorización matemática densa a Ollama."""
    try:
        respuesta = requests.post(
            OLLAMA_URL,
            json={"model": "nomic-embed-text", "prompt": texto},
            timeout=(5, 30),
        )
        if respuesta.status_code == 200:
            return respuesta.json().get("embedding")
        return None
    except Exception as exc:
        print(f"[ERROR OLLAMA] Falla de conexión: {str(exc)}")
        return None


def obtener_sparse_embedder():
    """Carga el modelo sparse BM25 de FastEmbed para indexar palabras clave."""
    global _SPARSE_EMBEDDER
    if _SPARSE_EMBEDDER is not None:
        return _SPARSE_EMBEDDER

    try:
        from fastembed import SparseEmbedding
    except ImportError as exc:
        raise RuntimeError("Falta la dependencia fastembed. Instala: pip install fastembed") from exc

    _SPARSE_EMBEDDER = SparseEmbedding(model_name="Qdrant/bm25")
    return _SPARSE_EMBEDDER


def generar_sparse_vector(texto, sparse_embedder=None):
    """Genera un vector disperso BM25 para un fragmento de texto."""
    if not texto:
        return None

    sparse_embedder = sparse_embedder or obtener_sparse_embedder()
    embedding = next(sparse_embedder.embed([texto]))

    if isinstance(embedding, dict):
        indices = list(embedding.get("indices", []))
        values = list(embedding.get("values", []))
    else:
        indices = list(getattr(embedding, "indices", []))
        values = list(getattr(embedding, "values", []))

    if not indices or not values:
        return None

    return {"indices": indices, "values": values}


def preparar_coleccion_hibrida(cliente):
    """Crea la colección con vectores densos y sparse si aún no existe."""
    if cliente.collection_exists(collection_name=COLECCION):
        return

    cliente.create_collection(
        collection_name=COLECCION,
        vectors_config={
            "dense": VectorParams(size=768, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))
        },
    )


def _ajustar_bloque_final(fragmentos, max_caracteres, overlap):
    """Une el último fragmento si queda demasiado corto para mantener continuidad."""
    if len(fragmentos) < 2:
        return fragmentos

    ultimo = fragmentos[-1]
    penultimo = fragmentos[-2]
    if len(ultimo) < overlap and len(penultimo) + len(ultimo) <= max_caracteres:
        fragmentos[-2] = f"{penultimo.strip()}\n\n{ultimo.strip()}".strip()
        fragmentos.pop()
    return fragmentos


def dividir_en_fragmentos(texto, max_caracteres=1000, overlap=200):
    """Divide el texto en fragmentos con limitación de longitud y solapamiento fijo."""
    if max_caracteres <= 0:
        raise ValueError("max_caracteres debe ser mayor que cero.")
    if overlap >= max_caracteres:
        raise ValueError("El overlap debe ser menor que max_caracteres.")

    texto_limpio = limpiar_texto(texto)
    if not texto_limpio:
        return []

    fragmentos = []
    inicio = 0
    longitud = len(texto_limpio)

    while inicio < longitud:
        fin = min(inicio + max_caracteres, longitud)
        if fin < longitud and (longitud - fin) < overlap:
            fin = longitud
        fragmento = texto_limpio[inicio:fin].strip()
        if fragmento:
            fragmentos.append(fragmento)

        if fin == longitud:
            break
        inicio += max_caracteres - overlap

    fragmentos = _ajustar_bloque_final(fragmentos, max_caracteres, overlap)
    return [fragmento for fragmento in fragmentos if len(fragmento) > 50]


fragmentar_texto = dividir_en_fragmentos


def vectorizar_documento(ruta_pdf, nombre_archivo):
    """Lee, limpia, fragmenta e ingesta un documento PDF en Qdrant con búsqueda híbrida."""
    texto_crudo = extraer_texto_pdf(ruta_pdf)
    if not texto_crudo:
        raise ValueError("El PDF está vacío o no se pudo leer el texto.")

    fragmentos = dividir_en_fragmentos(texto_crudo, max_caracteres=1000, overlap=200)
    if not fragmentos:
        raise RuntimeError("No se generaron fragmentos válidos a partir del documento.")

    cliente = QdrantClient(host=QDRANT_HOST, port=6333)
    preparar_coleccion_hibrida(cliente)

    puntos_qdrant = []
    marca_ingesta = datetime.now(timezone.utc).isoformat()
    sparse_embedder = obtener_sparse_embedder()

    for indice, fragmento in enumerate(fragmentos, start=1):
        vector_denso = obtener_embedding(fragmento)
        vector_sparse = generar_sparse_vector(fragmento, sparse_embedder)
        if not vector_denso or not vector_sparse:
            continue

        payload = {
            "texto": fragmento,
            "origen": nombre_archivo,
            "source": nombre_archivo,
            "bloque": indice,
            "block_number": indice,
            "timestamp_ingesta": marca_ingesta,
            "ingested_at": marca_ingesta,
            "documento": nombre_archivo,
        }
        puntos_qdrant.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    "dense": vector_denso,
                    "sparse": SparseVector(
                        indices=vector_sparse["indices"],
                        values=vector_sparse["values"],
                    ),
                },
                payload=payload,
            )
        )

    if not puntos_qdrant:
        raise RuntimeError("No se generaron vectores válidos para inyectar.")

    cliente.upsert(collection_name=COLECCION, points=puntos_qdrant)
    return len(puntos_qdrant)
