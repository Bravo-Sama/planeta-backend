import os
from django.shortcuts import render
from .extractor import procesar_pdf
from rag_engine.vectorizador import procesar_y_guardar_vectores

def panel_ingesta(request):
    texto = ""
    fragmentos_guardados = 0
    
    if request.method == 'POST' and request.FILES.get('documento_pdf'):
        archivo = request.FILES['documento_pdf']
        
        # 1. Definimos las rutas
        ruta_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ruta_carpeta_docs = os.path.join(ruta_base, 'documentos')
        ruta_guardado = os.path.join(ruta_carpeta_docs, archivo.name)
        
        # 2. EL BLINDAJE: Si la carpeta 'documentos' no existe, la creamos
        if not os.path.exists(ruta_carpeta_docs):
            os.makedirs(ruta_carpeta_docs)
        
        # 3. Guardamos el archivo físicamente
        with open(ruta_guardado, 'wb+') as destination:
            for chunk in archivo.chunks():
                destination.write(chunk)
                
        # 4. El satélite limpiador saca el texto
        texto = procesar_pdf(archivo.name)
        
        # 5. El motor RAG vectoriza y guarda en base de datos
        if texto:
            fragmentos_guardados = procesar_y_guardar_vectores(texto)
        
    return render(request, 'satelite_limpiador/ingesta.html', {
        'texto_extraido': texto, 
        'fragmentos': fragmentos_guardados
    })