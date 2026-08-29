import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rag_engine.buscador import hacer_pregunta
import psutil
from django.shortcuts import render

# --- NUEVA VISTA PARA LA INTERFAZ HTML ---
def vista_chat(request):
    return render(request, 'api_central/chat.html')

# --- ENDPOINT DE LA API (Para n8n y la interfaz web) ---
# Apagamos la protección CSRF solo para este endpoint porque n8n (o el fetch de JS) se conectará de forma automatizada
@csrf_exempt 
def endpoint_preguntar(request):
    if request.method == 'POST':
        try:
            # 1. Recibimos el mensaje desde n8n o el chat HTML
            data = json.loads(request.body)
            pregunta = data.get('pregunta', '')
            
            if not pregunta:
                return JsonResponse({'error': 'No se recibió ninguna pregunta.'}, status=400)
            
            # 2. Despertamos al motor RAG de Planeta
            respuesta_ia = hacer_pregunta(pregunta)
            
            # 3. Empaquetamos la respuesta para devolverla a n8n / frontend
            return JsonResponse({'respuesta': respuesta_ia}, status=200)
        
        except Exception as e:
            import traceback
            traceback.print_exc() # Esto imprimirá el error real en la terminal
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Método no permitido. Debes usar POST.'}, status=405)

def dashboard_view(request):
    # 1. Leer métricas reales de hardware (del servidor/contenedor)
    ram_usage = psutil.virtual_memory().percent
    disk_usage = psutil.disk_usage('/').percent
    
    # 2. Consultar métricas del sistema RAG
    # TODO: A futuro, esto será un `.count()` a tu base de datos de Redis/MariaDB
    total_inferencias = 150  # Por ahora usaremos un valor simulado
    
    # 3. Empaquetar los datos en un "contexto" para enviarlos al HTML
    context = {
        'ram_usage': ram_usage,
        'disk_usage': disk_usage,
        'total_inferencias': total_inferencias,
    }
    
    return render(request, 'api_central/dashboard_admin.html', context)