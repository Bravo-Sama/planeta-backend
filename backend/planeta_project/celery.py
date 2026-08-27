import os
from celery import Celery

# Le decimos a Celery qué archivo de configuración de Django usar
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'planeta_project.settings')

# Nombramos nuestra app de Celery como 'planeta'
app = Celery('planeta')

# Le decimos que lea la configuración de Celery desde el settings.py de Django
app.config_from_object('django.conf:settings', namespace='CELERY')

# Esto hace que Celery busque tareas automáticas en tus satélites
app.autodiscover_tasks()