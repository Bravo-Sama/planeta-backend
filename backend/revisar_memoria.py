from qdrant_client import QdrantClient

print("Conectando a los bancos de memoria vectorial (Qdrant)...")

try:
    # Conectamos a Qdrant usando el nombre del contenedor de Docker
    cliente = QdrantClient(host="qdrant", port=6333)
    coleccion = "aguas_decimas"
    
    # Obtenemos la información de la colección
    info = cliente.get_collection(collection_name=coleccion)
    cantidad = info.points_count
    
    print(f"\n¡Conexión exitosa!")
    print(f"Colección activa: '{coleccion}'")
    print(f"Total de fragmentos matemáticos almacenados: {cantidad}")
    
    # Extraemos el primer recuerdo para comprobar que el texto sigue ahí
    if cantidad > 0:
        print("\n--- Muestra del primer recuerdo en la base de datos ---")
        muestra, _ = cliente.scroll(
            collection_name=coleccion, 
            limit=1,
            with_payload=True # Esto le dice que traiga el texto, no solo los números
        )
        texto_guardado = muestra[0].payload.get('texto', 'Sin texto')
        print(texto_guardado[:200] + " [...]")
        print("-------------------------------------------------------")

except Exception as e:
    print(f"\nError al leer la base de datos: {e}")
    