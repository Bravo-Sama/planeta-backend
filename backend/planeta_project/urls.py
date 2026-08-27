from django.contrib import admin
from django.urls import path
from satelite_limpiador.views import panel_ingesta

urlpatterns = [
    path('admin/', admin.site.urls),
    path('ingesta/', panel_ingesta, name='ingesta_documentos'),
]
