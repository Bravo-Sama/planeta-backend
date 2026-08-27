import fitz  # Esta es la librería PyMuPDF
import os

def procesar_pdf(nombre_archivo):
    # Armamos la ruta exacta hacia la carpeta 'documentos'
    ruta_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ruta_pdf = os.path.join(ruta_base, 'documentos', nombre_archivo)
    
    print(f"Iniciando extracción de: {ruta_pdf}")
    texto_completo = ""

    try:
        # Abrimos el documento PDF
        doc = fitz.open(ruta_pdf)
        
        # Recorremos cada página
        for numero_pagina, pagina in enumerate(doc):
            # Extraemos solo el texto puro
            texto_pagina = pagina.get_text("text")
            
            # (Más adelante aquí agregaremos filtros para borrar números de página o marcas de agua)
            
            texto_completo += texto_pagina + "\n\n"
            
        print(f"¡Éxito! Se procesaron {len(doc)} páginas limpias.")
        return texto_completo

    except Exception as e:
        print(f"Error crítico al leer el PDF: {e}")
        return None