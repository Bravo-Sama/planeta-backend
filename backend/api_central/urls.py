from django.urls import path
from . import views

urlpatterns = [
    path('chat/', views.vista_chat, name='chat'),
    path('preguntar/', views.endpoint_preguntar, name='preguntar'),
    path('registro/', views.registro_view, name='registro'),
    path('recuperar-password/', views.recuperar_password_view, name='recuperar_password'),
    path('reset-password/', views.reset_password_view, name='reset_password'),
    path('subida-documentos/', views.subida_documentos_view, name='subida_documentos'),
    path('gestion-rag/', views.gestion_rag_view, name='gestion_rag'),
    path('faq-sistema/', views.faq_sistema_view, name='faq_sistema'),
    path('historial-chats/', views.historial_chats_view, name='historial_chats'),
    path('configuracion-ia/', views.configuracion_ia_view, name='configuracion_ia'),
]
