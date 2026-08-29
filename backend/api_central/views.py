import json
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rag_engine.buscador import hacer_pregunta

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

