import requests
import uuid
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# Rutas de conexión
OLLAMA_URL = "http://host.docker.internal:11434/api/embeddings"
QDRANT_HOST = "qdrant"
COLECCION = "aguas_decimas"

def dividir_en_chunks(texto, tamano=700, solape=150):
    """Corta el texto largo en fragmentos más pequeños con un poco de solapamiento para no perder contexto"""
    chunks = []
    inicio = 0
    while inicio < len(texto):
        fin = inicio + tamano
        chunks.append(texto[inicio:fin])
        inicio += (tamano - solape)
    return chunks

def obtener_embedding(texto):
    """Le pide a Ollama que convierta el texto en coordenadas matemáticas"""
    payload = {
        "model": "nomic-embed-text",
        "prompt": texto
    }
    respuesta = requests.post(OLLAMA_URL, json=payload, timeout=(5, 30))
    if respuesta.status_code == 200:
        return respuesta.json()["embedding"]
    print(f"Error al conectar con Ollama: {respuesta.text}")
    return None

def procesar_y_guardar_vectores(texto_limpio):
    """Orquesta todo el proceso y guarda en Qdrant"""
    cliente = QdrantClient(host=QDRANT_HOST, port=6333)
    
    # 1. Crear el cajón en Qdrant si no existe (nomic-embed-text usa 768 dimensiones)
    if not cliente.collection_exists(collection_name=COLECCION):
        cliente.create_collection(
            collection_name=COLECCION,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
    
    # 2. Cortar el texto
    fragmentos = dividir_en_chunks(texto_limpio)
    puntos = []
    
    # 3. Traducir cada fragmento y prepararlo
    print(f"Vectorizando {len(fragmentos)} fragmentos...")
    for fragmento in fragmentos:
        vector = obtener_embedding(fragmento)
        if vector:
            punto = PointStruct(
                id=str(uuid.uuid4()), # Genera un ID único al azar
                vector=vector,
                payload={"texto": fragmento} # Guardamos el texto original junto al vector
            )
            puntos.append(punto)
            
    # 4. Inyectar en la base de datos
    if puntos:
        cliente.upsert(
            collection_name=COLECCION,
            points=puntos
        )
        print("¡Inyección en Qdrant completada!")
        return len(puntos)
    return 0