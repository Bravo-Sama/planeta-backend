import requests
from qdrant_client import QdrantClient
from .vectorizador import obtener_embedding

OLLAMA_CHAT_URL = "http://host.docker.internal:11434/api/generate"
QDRANT_HOST = "qdrant"
COLECCION = "aguas_decimas"

def hacer_pregunta(pregunta_usuario):
    print(f"Pregunta recibida: {pregunta_usuario}")
    
    # 1. Convertimos la pregunta a vectores
    vector_pregunta = obtener_embedding(pregunta_usuario)
    if not vector_pregunta:
        return "Error: No pude vectorizar la pregunta."

    # 2. Buscamos en los archivos de Aguas Décimas usando la nueva sintaxis de Qdrant
    print("Buscando en la base de datos...")
    cliente = QdrantClient(host=QDRANT_HOST, port=6333)
    
    consulta = cliente.query_points(
        collection_name=COLECCION,
        query=vector_pregunta,
        limit=3  # Traemos los 3 fragmentos más relevantes
    )
    
    resultados = consulta.points

    # 3. Armamos el contexto con los resultados
    contexto_recuperado = "\n\n".join([hit.payload['texto'] for hit in resultados])
    print(f"Encontré {len(resultados)} fragmentos útiles. Pensando la respuesta...")

    # 4. Le pedimos a Llama 3 que redacte la respuesta final
    prompt_experto = f"""
    Eres un asistente técnico experto. Responde la pregunta del usuario basándote ÚNICAMENTE en la siguiente información de contexto.
    Si la respuesta no está en el contexto, di que no tienes esa información.
    
    Contexto:
    {contexto_recuperado}
    
    Pregunta: {pregunta_usuario}
    """

    payload = {
        "model": "llama3",
        "prompt": prompt_experto,
        "stream": False
    }

    respuesta = requests.post(OLLAMA_CHAT_URL, json=payload)
    if respuesta.status_code == 200:
        return respuesta.json()['response']
    
    return "Hubo un error de comunicación con el cerebro de Llama 3."