"""
Módulo de Configuración del Panel de Administración.

Expone los modelos del sistema a la interfaz gráfica de Django
para permitir operaciones CRUD de manera segura.
"""

from django.contrib import admin
from .models import RespuestaFrecuente, DocumentoPendiente

@admin.register(RespuestaFrecuente)
class RespuestaFrecuenteAdmin(admin.ModelAdmin):
    list_display = ('pregunta_estandar', 'frecuencia_uso', 'fecha_actualizacion')
    search_fields = ('pregunta_estandar', 'respuesta_aprobada')
    readonly_fields = ('frecuencia_uso', 'fecha_creacion', 'fecha_actualizacion')


@admin.register(DocumentoPendiente)
class DocumentoPendienteAdmin(admin.ModelAdmin):
    """
    Configuración de visualización para la cola de ingesta diferida de PDFs.
    """
    list_display = ('nombre_archivo', 'estado', 'fecha_subida', 'fecha_procesamiento')
    
    # Permite filtrar rápidamente en el panel para ver qué falló o qué falta por procesar
    list_filter = ('estado',)
    search_fields = ('nombre_archivo',)
    
    # Protege las marcas de tiempo generadas por el sistema
    readonly_fields = ('fecha_subida', 'fecha_procesamiento')