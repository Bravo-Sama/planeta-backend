"""Configuración central de Django para Planeta.

Este módulo valida y carga todas las variables críticas de entorno al inicio del
arranque para evitar estados parcialmente inicializados y hosts fijos quemados en
el código.
"""

import logging
import logging.config
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def require_env(name):
    """Levanta un error de arranque si falta una variable crítica."""
    value = os.getenv(name)
    if value is None or value.strip() == '':
        sys.stderr.write(f"Falta la variable de entorno requerida: {name}\n")
        sys.exit(1)
    return value


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'planeta': {
            'format': '[%(asctime)s] [%(levelname)s] [%(module)s] [%(chat_id)s] [%(tiempo_ms)s] - %(message)s',
            'datefmt': '%Y-%m-%dT%H:%M:%S%z',
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'planeta',
            'level': 'INFO',
        }
    },
    'loggers': {
        'planeta': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'root': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    },
}

logging.config.dictConfig(LOGGING)


# --- CONFIGURACIÓN DE SEGURIDAD Y ENTORNO ---
SECRET_KEY = require_env('SECRET_KEY')
DEBUG = require_env('DEBUG').lower() in ('1', 'true', 'yes', 'on')
ALLOWED_HOSTS = require_env('ALLOWED_HOSTS').split(',')

# --- CONFIGURACIÓN DE BASE DE DATOS ---
DB_NAME = require_env('DB_NAME')
DB_USER = require_env('DB_USER')
DB_PASSWORD = require_env('DB_PASSWORD')
DB_HOST = require_env('DB_PROXY_HOST')
DB_PORT = int(require_env('DB_PROXY_PORT'))
DB_CONN_MAX_AGE = 0
DB_POOL_MIN_SIZE = int(require_env('DB_POOL_MIN_SIZE'))
DB_POOL_MAX_SIZE = int(require_env('DB_POOL_MAX_SIZE'))

# --- CONFIGURACIÓN DE REDIS Y SERVICIOS EXTERNOS ---
REDIS_HOST = require_env('REDIS_HOST')
REDIS_PORT = int(require_env('REDIS_PORT'))
QDRANT_HOST = require_env('QDRANT_HOST')
QDRANT_PORT = int(require_env('QDRANT_PORT'))
QDRANT_COLLECTION = require_env('QDRANT_COLLECTION')
OLLAMA_BASE_URL = require_env('OLLAMA_BASE_URL')
OLLAMA_MODEL = require_env('OLLAMA_MODEL')
OLLAMA_EMBEDDINGS_MODEL = require_env('OLLAMA_EMBEDDINGS_MODEL')
MODELO_CLASIFICACION = require_env('MODELO_CLASIFICACION')
TELEGRAM_TOKEN = require_env('TELEGRAM_TOKEN')
TELEGRAM_BOT_TOKEN = TELEGRAM_TOKEN
TELEGRAM_SECRET_TOKEN = require_env('TELEGRAM_SECRET_TOKEN')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'api_central',
    'satelite_limpiador',
    'rag_engine',
    'satelite_telegram',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'planeta_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'planeta_project.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': DB_NAME,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'HOST': DB_HOST,
        'PORT': DB_PORT,
        'CONN_MAX_AGE': DB_CONN_MAX_AGE,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'sql_mode': 'STRICT_TRANS_TABLES',
            'connect_timeout': 10,
            'read_timeout': 30,
            'write_timeout': 30,
            'autocommit': True,
            'init_command': "SET SESSION sql_mode='STRICT_TRANS_TABLES'",
        },
        'TEST': {
            'CHARSET': 'utf8mb4',
        },
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = require_env('LANGUAGE_CODE')
TIME_ZONE = require_env('TIME_ZONE')

USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- CONFIGURACIÓN DE REDIS Y CELERY ---
CELERY_BROKER_URL = require_env('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = require_env('CELERY_RESULT_BACKEND')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TIME_LIMIT = int(require_env('CELERY_TASK_TIME_LIMIT'))
CELERY_TASK_SOFT_TIME_LIMIT = int(require_env('CELERY_TASK_SOFT_TIME_LIMIT'))
CELERY_WORKER_CONCURRENCY = 4
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_DEFAULT_QUEUE = 'default'

# --- CONFIGURACIÓN CELERY BEAT (SATÉLITE NOCTURNO) ---
if require_env('ENABLE_CELERY_BEAT').lower() in ('1', 'true', 'yes', 'on'):
    from celery.schedules import crontab
    CELERY_BEAT_SCHEDULE = {
        'vectorizacion-nocturna-pdfs': {
            'task': 'satelite_telegram.tasks.procesar_documentos_pendientes',
            'schedule': crontab(minute=0, hour=3),
        },
    }
else:
    CELERY_BEAT_SCHEDULE = {}
