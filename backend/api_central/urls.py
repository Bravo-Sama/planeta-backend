from django.urls import path
from . import views

urlpatterns = [
    path('chat/', views.vista_chat, name='chat'),
    path('preguntar/', views.endpoint_preguntar, name='preguntar'),
]
