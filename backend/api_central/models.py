from django.db import models

# Create your models here.
class Inferencia(models.Model):
    pregunta = models.TextField()
    respuesta = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Inferencia {self.id} - {self.fecha.strftime('%d/%m/%Y %H:%M')}"