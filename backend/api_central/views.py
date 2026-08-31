import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rag_engine.buscador import hacer_pregunta
import psutil
from django.shortcuts import render
from .models import Inferencia
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User


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
            Inferencia.objects.create(pregunta=pregunta, respuesta=respuesta_ia)
            # 3. Empaquetamos la respuesta para devolverla a n8n / frontend
            return JsonResponse({'respuesta': respuesta_ia}, status=200)
        
        except Exception as e:
            import traceback
            traceback.print_exc() # Esto imprimirá el error real en la terminal
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Método no permitido. Debes usar POST.'}, status=405)

@login_required(login_url='/login/')
def dashboard_view(request):
    # 1. Leer métricas reales de hardware (del servidor/contenedor)
    ram_usage = psutil.virtual_memory().percent
    disk_usage = psutil.disk_usage('/').percent
    total_inferencias = Inferencia.objects.count()
    
    # 2. Consultar métricas del sistema RAG
    context = {
        'ram_usage': ram_usage,
        'disk_usage': disk_usage,
        'total_inferencias': total_inferencias,
    } 
    
    return render(request, 'api_central/dashboard_admin.html', context)

# --- VISTA DEL LOGIN ---
def login_view(request):
    if request.method == 'POST':
        # 1. Atrapamos lo que el usuario escribió en el HTML
        usuario = request.POST.get('username')
        clave = request.POST.get('password')
        
        # 2. Django revisa MariaDB para ver si la llave maestra es correcta
        user = authenticate(request, username=usuario, password=clave)
        
        if user is not None:
            # 3. ¡Es correcto! Le abrimos la puerta y lo mandamos al dashboard
            login(request, user)
            return redirect('dashboard_admin')
        else:
            # 4. ¡Se equivocó! Lo devolvemos al login con un mensaje de error
            return render(request, 'api_central/login.html', {'error': 'Usuario o contraseña incorrectos'})
            
    # Si entra por GET (solo está mirando la página), mostramos el formulario vacío
    return render(request, 'api_central/login.html')

# --- VISTA PARA CERRAR SESIÓN ---
def logout_view(request):
    logout(request) # Esto destruye la sesión segura en el servidor
    return redirect('login_root') # Lo mandamos de vuelta a la pantalla inicial

# --- VISTA DE GESTIÓN DE USUARIOS ---
@login_required(login_url='/login/')
def usuarios_view(request):
    # Traemos todos los usuarios registrados, ordenados por los más recientes
    lista_usuarios = User.objects.filter(is_superuser=False).order_by('-date_joined')
    return render(request, 'api_central/usuarios.html', {'usuarios': lista_usuarios})

@login_required(login_url='/login/')
def crear_usuario_view(request):
    if request.method == 'POST':
        nombre_usuario = request.POST.get('username')
        correo = request.POST.get('email')
        clave = request.POST.get('password')
        
        # 1. EL FILTRO Corporativo
        if not correo.endswith('@tuempresa.cl'):
            return JsonResponse({'success': False, 'error': 'Acceso denegado: Solo se permiten correos terminados en @tuempresa.cl'})
        
        # 2. Verificamos duplicados
        if User.objects.filter(username=nombre_usuario).exists():
            return JsonResponse({'success': False, 'error': 'Ese nombre de usuario ya está registrado.'})
            
        # 3. Guardado seguro
        User.objects.create_user(username=nombre_usuario, email=correo, password=clave)
        
        return JsonResponse({'success': True})
    
# --- VISTA PARA PAUSAR O ELIMINAR USUARIOS ---
@login_required(login_url='/login/')
def accion_usuario_view(request, usuario_id, accion):
    # Buscamos al usuario por su ID
    usuario = get_object_or_404(User, id=usuario_id)
    
    # Doble seguridad: Nunca permitimos que esta función altere a un Superusuario
    if not usuario.is_superuser:
        if accion == 'pausar':
            # Si está activo lo pausa, si está pausado lo activa (switch)
            usuario.is_active = not usuario.is_active
            usuario.save()
            
        elif accion == 'eliminar':
            usuario.delete()
            
    # Finalmente, recargamos la tabla
    return redirect('gestion_usuarios')

# --- VISTA PARA EDITAR USUARIOS (AJAX) ---
@login_required(login_url='/login/')
def editar_usuario_view(request, usuario_id):
    if request.method == 'POST':
        usuario = get_object_or_404(User, id=usuario_id)
        
        # Protegemos al superusuario por si acaso
        if usuario.is_superuser:
            return JsonResponse({'success': False, 'error': 'No puedes editar al administrador aquí.'})

        nuevo_nombre = request.POST.get('username')
        nuevo_correo = request.POST.get('email')
        
        # 1. Filtro Corporativo
        if not nuevo_correo.endswith('@tuempresa.cl'):
            return JsonResponse({'success': False, 'error': 'Solo se permiten correos terminados en @tuempresa.cl'})
        
        # 2. Verificamos que el nuevo nombre no esté siendo usado por OTRO usuario
        if User.objects.filter(username=nuevo_nombre).exclude(id=usuario_id).exists():
            return JsonResponse({'success': False, 'error': 'Ese nombre de usuario ya pertenece a otra persona.'})
            
        # 3. Guardamos los cambios
        usuario.username = nuevo_nombre
        usuario.email = nuevo_correo
        usuario.save()
        
        return JsonResponse({'success': True})
    
# --- VISTA PARA CAMBIAR CONTRASEÑA (AJAX) ---
@login_required(login_url='/login/')
def cambiar_password_view(request, usuario_id):
    if request.method == 'POST':
        usuario = get_object_or_404(User, id=usuario_id)
        
        # Nunca permitimos cambiar la clave del superusuario desde aquí por seguridad
        if usuario.is_superuser:
            return JsonResponse({'success': False, 'error': 'No puedes alterar al administrador.'})

        nueva_clave = request.POST.get('new_password')
        
        # Una pequeña validación de seguridad
        if len(nueva_clave) < 6:
            return JsonResponse({'success': False, 'error': 'La contraseña debe tener al menos 6 caracteres.'})

        # 1. Encriptamos y asignamos la nueva clave
        usuario.set_password(nueva_clave)
        # 2. Guardamos en la base de datos
        usuario.save()
        
        return JsonResponse({'success': True})


# --- VISTAS DEL PROTOTIPO FUNCIONAL DEL PANEL ---
@login_required(login_url='/login/')
def subida_documentos_view(request):
    return render(request, 'api_central/subida_documentos.html')


@login_required(login_url='/login/')
def gestion_rag_view(request):
    return render(request, 'api_central/gestion_rag.html')


@login_required(login_url='/login/')
def faq_sistema_view(request):
    return render(request, 'api_central/faq_sistema.html')


@login_required(login_url='/login/')
def historial_chats_view(request):
    return render(request, 'api_central/historial_chats.html')


@login_required(login_url='/login/')
def configuracion_ia_view(request):
    return render(request, 'api_central/configuracion_ia.html')


def registro_view(request):
    return render(request, 'api_central/registro.html')


def recuperar_password_view(request):
    return render(request, 'api_central/recuperar_password.html')


def reset_password_view(request):
    return render(request, 'api_central/reset.html')
    
    
# --- VISTAS DE ERROR PERSONALIZADAS ---
def error_404_view(request, exception):
    return render(request, 'api_central/404.html', status=404)

def error_500_view(request):
    return render(request, 'api_central/500.html', status=500)

