"""
Módulo de Modelos de Base de Datos para el Satélite Telegram.

Define la estructura relacional (MariaDB) para almacenar la Base de 
Respuestas Frecuentes (FAQ Determinista). Este módulo es fundamental para
la estrategia de reducción de costos computacionales, actuando como la 
fuente de verdad para respuestas de latencia cero.
"""

from django.db import models


class RespuestaFrecuente(models.Model):
    """
    Entidad que almacena preguntas estandarizadas y sus respuestas oficiales.
    
    Cada registro almacenado aquí representa una consulta recurrente que 
    el sistema debe interceptar antes de activar el motor de inferencia (LLM).
    El campo 'pregunta_estandar' se utilizará posteriormente para generar 
    un vector en Qdrant y permitir búsquedas por similitud matemática.
    """
    
    pregunta_estandar = models.CharField(
        max_length=255, 
        unique=True,
        help_text="Pregunta base que será vectorizada para la comparación de similitud."
    )
    
    respuesta_aprobada = models.TextField(
        help_text="Respuesta técnica oficial que se enviará al usuario (evita el uso de la GPU)."
    )
    
    frecuencia_uso = models.PositiveIntegerField(
        default=0,
        help_text="Contador estadístico de cuántas veces el sistema ha interceptado y reciclado esta respuesta."
    )
    
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        help_text="Fecha y hora de registro de la FAQ."
    )
    
    fecha_actualizacion = models.DateTimeField(
        auto_now=True,
        help_text="Fecha y hora de la última modificación de la respuesta."
    )

    class Meta:
        verbose_name = "Respuesta Frecuente"
        verbose_name_plural = "Respuestas Frecuentes"
        # Ordena los registros mostrando los más utilizados primero
        ordering = ['-frecuencia_uso']

    def __str__(self):
        """Representación en cadena para el panel de administración."""
        return f"{self.pregunta_estandar} (Usos: {self.frecuencia_uso})"

class DocumentoPendiente(models.Model):
    """
    Entidad que registra los documentos PDF subidos al sistema para su procesamiento diferido.
    
    El Satélite Nocturno (Celery Beat) consultará esta tabla de madrugada para
    extraer y vectorizar los documentos en estado 'PENDIENTE', protegiendo así
    la memoria RAM y la GPU durante los horarios de alto tráfico de usuarios.
    """
    
    ESTADOS_PROCESAMIENTO = [
        ('PENDIENTE', 'Pendiente de Ingesta'),
        ('PROCESANDO', 'Vectorizando en Qdrant...'),
        ('COMPLETADO', 'Ingesta Exitosa'),
        ('ERROR', 'Error en Procesamiento'),
    ]

    nombre_archivo = models.CharField(
        max_length=255, 
        help_text="Nombre original del documento (ej. NCh2485_2000.pdf)."
    )
    
    archivo = models.FileField(
        upload_to='documentos_pendientes/', 
        help_text="Ruta física del archivo almacenado temporalmente en el servidor."
    )
    
    estado = models.CharField(
        max_length=15, 
        choices=ESTADOS_PROCESAMIENTO, 
        default='PENDIENTE',
        help_text="Fase actual del documento en el pipeline de IA."
    )
    
    fecha_subida = models.DateTimeField(
        auto_now_add=True,
        help_text="Momento exacto en que el usuario o administrador subió el PDF."
    )
    
    fecha_procesamiento = models.DateTimeField(
        null=True, 
        blank=True, 
        help_text="Marca de tiempo en la que el Satélite Nocturno finalizó la vectorización."
    )

    class Meta:
        verbose_name = "Documento Pendiente"
        verbose_name_plural = "Documentos Pendientes"
        # Prioriza los documentos más antiguos para mantener un orden de llegada justo (FIFO)
        ordering = ['fecha_subida']

    def __str__(self):
        """Representación en cadena para el panel de administración."""
        return f"{self.nombre_archivo} - Estado: {self.get_estado_display()}"