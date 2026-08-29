"""
Módulo de Extracción e Ingesta de Documentos (RAG Engine).

Proporciona las herramientas para leer archivos PDF, fragmentar su contenido
y vectorizarlos en Qdrant utilizando Ollama. Diseñado para ser invocado 
de forma asíncrona por el Satélite Nocturno (Celery).
"""

import uuid
import fitz  # PyMuPDF
import requests
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

# Variables de entorno y configuración
QDRANT_HOST = "qdrant"
COLECCION = "aguas_decimas"
OLLAMA_URL = "http://host.docker.internal:11434/api/embeddings"


def extraer_texto_pdf(ruta_pdf):
    """Extrae el texto crudo de un archivo PDF."""
    try:
        doc = fitz.open(ruta_pdf)
        texto = "".join([pagina.get_text("text") + "\n\n" for pagina in doc])
        return texto
    except Exception as e:
        raise RuntimeError(f"Error crítico al leer el PDF {ruta_pdf}: {str(e)}")


def obtener_embedding(texto):
    """Solicita la vectorización matemática a Ollama."""
    try:
        respuesta = requests.post(OLLAMA_URL, json={
            "model": "nomic-embed-text",
            "prompt": texto
        }, timeout=120)
        
        if respuesta.status_code == 200:
            return respuesta.json().get('embedding')
        return None
    except Exception as e:
        print(f"[ERROR OLLAMA] Falla de conexión: {str(e)}")
        return None


def dividir_en_fragmentos(texto, max_caracteres=1000):
    """Divide el texto extenso en bloques semánticos manejables para la IA."""
    parrafos = texto.split('\n\n')
    fragmentos, fragmento_actual = [], ""
    
    for p in parrafos:
        if len(fragmento_actual) + len(p) < max_caracteres:
            fragmento_actual += p + "\n\n"
        else:
            if fragmento_actual.strip():
                fragmentos.append(fragmento_actual.strip())
            fragmento_actual = p + "\n\n"
            
    if fragmento_actual.strip():
        fragmentos.append(fragmento_actual.strip())
        
    return [f for f in fragmentos if len(f) > 50]


def vectorizar_documento(ruta_pdf, nombre_archivo):
    """
    Función principal de ingesta. 
    Orquesta la lectura, fragmentación e inyección en Qdrant de un solo documento.
    """
    texto_crudo = extraer_texto_pdf(ruta_pdf)
    if not texto_crudo:
        raise ValueError("El PDF está vacío o no se pudo leer el texto.")

    fragmentos = dividir_en_fragmentos(texto_crudo)
    cliente = QdrantClient(host=QDRANT_HOST, port=6333)
    puntos_qdrant = []

    for i, fragmento in enumerate(fragmentos):
        vector = obtener_embedding(fragmento)
        if vector:
            puntos_qdrant.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        "texto": fragmento,
                        "origen": nombre_archivo,
                        "bloque": i + 1
                    }
                )
            )

    if puntos_qdrant:
        cliente.upsert(collection_name=COLECCION, points=puntos_qdrant)
        return len(puntos_qdrant)
    else:
        raise RuntimeError("No se generaron vectores válidos para inyectar.")