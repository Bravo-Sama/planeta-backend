import os
from celery import Celery

# Le decimos a Celery qué configuraciones de Django usar
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'planeta_project.settings')

# Instanciamos el motor de filas
app = Celery('planeta_project')

# Carga las configuraciones del settings.py usando el prefijo CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Busca tareas automáticamente en todos tus satélites (apps)
app.autodiscover_tasks()

