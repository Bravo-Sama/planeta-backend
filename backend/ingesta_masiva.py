import os
import uuid
import fitz  # PyMuPDF
import requests
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

QDRANT_HOST = "qdrant"
COLECCION = "aguas_decimas"
OLLAMA_URL = "http://host.docker.internal:11434/api/embeddings"

def procesar_pdf_local(ruta_pdf):
    try:
        doc = fitz.open(ruta_pdf)
        texto = ""
        for pagina in doc:
            texto += pagina.get_text("text") + "\n\n"
        return texto
    except Exception as e:
        print(f"Error crítico al leer el PDF: {e}")
        return None

def obtener_embedding_local(texto):
    try:
        respuesta = requests.post(OLLAMA_URL, json={
            "model": "nomic-embed-text",
            "prompt": texto
        }, timeout=(5, 30))
        if respuesta.status_code == 200:
            return respuesta.json().get('embedding')
        return None
    except:
        return None

def dividir_en_fragmentos(texto, max_caracteres=1000):
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

def iniciar_ingesta():
    ruta_base = os.path.dirname(os.path.abspath(__file__))
    ruta_docs = os.path.join(ruta_base, 'documentos')
    archivos = [f for f in os.listdir(ruta_docs) if f.endswith('.pdf')]
    
    if not archivos:
        print("No se encontraron PDFs en la carpeta 'documentos'.")
        return
        
    print(f"🚀 Iniciando subida masiva de {len(archivos)} documentos...")
    cliente = QdrantClient(host=QDRANT_HOST, port=6333)

    for archivo in archivos:
        print(f"\n--- Procesando: {archivo} ---")
        ruta_pdf = os.path.join(ruta_docs, archivo)
        texto_crudo = procesar_pdf_local(ruta_pdf)
        
        if not texto_crudo:
            print(f"⚠️ Se omitió {archivo} por error de lectura.")
            continue
            
        fragmentos = dividir_en_fragmentos(texto_crudo)
        print(f"Dividido en {len(fragmentos)} bloques. Vectorizando con Ollama...")
        
        puntos_qdrant = []
        for i, fragmento in enumerate(fragmentos):
            vector = obtener_embedding_local(fragmento)
            if vector:
                puntos_qdrant.append(
                    PointStruct(
                        id=str(uuid.uuid4()),
                        vector=vector,
                        payload={
                            "texto": fragmento,
                            "origen": archivo,
                            "bloque": i + 1
                        }
                    )
                )
        
        if puntos_qdrant:
            cliente.upsert(collection_name=COLECCION, points=puntos_qdrant)
            print(f"✅ {archivo} inyectado exitosamente en Qdrant ({len(puntos_qdrant)} vectores).")
        else:
            print(f"❌ Error al vectorizar {archivo}.")

if __name__ == "__main__":
    iniciar_ingesta()