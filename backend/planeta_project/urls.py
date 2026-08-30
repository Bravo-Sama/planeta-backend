from django import views
from django.contrib import admin
from django.urls import path, include
from api_central import views
from django.shortcuts import render

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/telegram/', include('satelite_telegram.urls')), 
    path('ingesta/', include('satelite_limpiador.urls')),
    path('api/', include('api_central.urls')),
    path('dashboard/', views.dashboard_view, name='dashboard_admin'),
    path('', views.login_view, name='login_root'),         # <-- La raíz del sitio web
    path('login/', views.login_view, name='login'),
    path('usuarios/', views.usuarios_view, name='gestion_usuarios'),
    path('usuarios/crear/', views.crear_usuario_view, name='crear_usuario'),
    path('usuarios/accion/<int:usuario_id>/<str:accion>/', views.accion_usuario_view, name='accion_usuario'),
    path('usuarios/editar/<int:usuario_id>/', views.editar_usuario_view, name='editar_usuario'),
    path('usuarios/password/<int:usuario_id>/', views.cambiar_password_view, name='cambiar_password'),
    path('logout/', views.logout_view, name='logout'),
]

handler404 = 'api_central.views.error_404_view'
handler500 = 'api_central.views.error_500_view'