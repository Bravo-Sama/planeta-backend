# 🪐 Planeta Backend

Planeta es un prototipo funcional de backend para un sistema de IA orientado a la gestión documental, búsqueda semántica y automatización asistida. El proyecto combina Django, Celery, Redis, MariaDB, Qdrant y Ollama para ofrecer una arquitectura modular pensada para RAG, atención a usuarios y conexión con Telegram.

El repositorio representa una fase de prototipo/beta de laboratorio: ya hay interfaz web operativa, integración con Telegram, motores de ingestión y orquestación RAG, pero aún se trabaja en la estabilización real del entorno de ejecución y la validación de servicios externos.

## Estado actual

- Prototipo funcional en desarrollo y validación.
- Backend Django operativo en contenedores.
- Workers Celery y Redis conectados correctamente.
- Servicios de base de datos y vector store activos en Docker.
- Interfaz administrativa creada con pantallas para login, registro, dashboard, gestión documental, RAG, FAQ y configuración.
- Integración con Telegram preparada y parcialmente validada con webhook y secreto compartido.
- No se recomienda tratar este estado como producción final: aún hay bloqueadores de infraestructura y seguridad que deben corregirse antes de asumir estabilidad operativa.

## Arquitectura general

La solución sigue una arquitectura modular con un núcleo central y satélites especializados:

- Core backend: Django
- Asincronía: Celery + Redis
- Datos relacionales: MariaDB
- Búsqueda vectorial: Qdrant
- IA local: Ollama
- Entrypoint público: Nginx
- Canal de interacción: Telegram

### Módulos principales

- `backend/planeta_project/`: configuración principal de Django, settings y servicios del sistema.
- `backend/api_central/`: interfaz web administrativa y endpoints del núcleo.
- `backend/rag_engine/`: lógica de búsqueda semántica, chunking, orquestación de RAG y circuit breakers.
- `backend/satelite_limpiador/`: ingestión y limpieza de documentos PDF.
- `backend/satelite_telegram/`: integración con Telegram, webhook, tareas y eventos.
- `backend/seguridad/`: utilidades de seguridad y validaciones.
- `backend/documentos/`: almacenamiento local de documentos recibidos.
- `docker-compose.yml`: orquestación de infraestructura interna.
- `nginx.conf`: enrutamiento HTTP y control de acceso público.

## Stack técnico

- Python 3.x + Django 5
- Celery 5
- Redis 7
- MariaDB 10.11
- Qdrant
- Ollama
- Nginx
- Docker + Docker Compose
- PyMuPDF, qdrant-client, sentence-transformers, fastembed, tenacity

## interfaz administrativa y prototipo web

Se han desarrollado vistas para cubrir el flujo principal del panel administrativo:

- Login
- Registro
- Recuperación de contraseña
- Reset de acceso
- Dashboard administrativo
- Subida masiva de documentos
- Gestión de RAG / documentos vectorizados
- FAQ del sistema
- Historial de chats
- Configuración de IA
- Páginas 404 y 500

Estas pantallas permiten validar la experiencia completa del producto y la navegación del backend sin depender de una versión final de negocio.

## Flujo principal del sistema

1. Un usuario accede a la interfaz web administrativa.
2. El backend valida credenciales y autoriza acceso al dashboard.
3. Un administrador sube documentos para ingesta documental.
4. El satélite limpiador procesa archivos PDF y genera contenido estructurado.
5. El motor RAG divide el contenido en fragmentos, genera embeddings y los almacena en Qdrant.
6. Las consultas semánticas se resuelven contra ese índice vectorial.
7. El modelo Ollama responde con contexto y se integra con la lógica de negocio.
8. La capa de Telegram recibe eventos desde bot externo y los enruta a tareas asincrónicas de Celery.
9. El sistema registra y audita resultados para validar respuestas, huellas de usuario y fallos.

## Requisitos y despliegue

### Prerrequisitos

- Docker
- Docker Compose
- Git
- Conexión a Internet para accesos externos y webhook de Telegram si se desea probar en red pública

### Inicio rápido

```bash
git clone https://github.com/Bravo-Sama/planeta-backend.git
cd planeta-backend

docker compose up --build -d
```

Para revisar logs:

```bash
docker compose logs -f backend

docker compose logs -f planeta_celery_worker
```

### Variables de entorno

Se usan archivos `.env` para la configuración de servicios internos. No se deben subir secretos reales al repositorio.

## Criterios de beta y riesgos conocidos

Este proyecto se encuentra en una fase beta controlada. La prioridad no es pulir el producto visual de forma exhaustiva, sino validar servicios reales y reducir riesgos funcionales.

### Lo que ya está funcionando

- Orquestación base con Django y Celery
- Integración Redis/Celery
- Infraestructura Docker y contenedores básicos
- Interfaz administrativa funcional como prototipo
- Flujo RAG y ingestión documentales en desarrollo activo
- Webhook de Telegram configurado por ruta real y validación de seguridad

### Lo que aún requiere trabajo real

- Validación persistente de conexiones a base de datos
- Estabilización de entorno entre contenedores y hosts internos
- Revisión temporal de NGINX/whitelist y seguridad HTTP
- Control de errores y observabilidad en producción de pruebas
- Métricas reales de uso, latencia y fallos de servicios
- Alineación definitiva de estrategias de token, autenticación y seguridad

## Roadmap de evolución

### Fase 1: estabilización del prototipo

- Validar todos los servicios Docker
- Corregir tiempos de arranque y dependencias internas
- Confirmar conexión correcta entre Django, Celery, Redis, MariaDB y Qdrant
- Verificar webhook de Telegram con secreto válido

### Fase 2: datos y observabilidad

- Añadir métricas esenciales
- Registrar errores con trazabilidad
- Medir volumen de RAG, latencia y calidad de respuesta
- Definir alertas para servicios críticos

### Fase 3: beta 1.0

- Consolidar auth y roles
- Revisar flujos de administración y seguridad
- Preparar despliegue de prueba con entorno controlado
- Documentar pasos de soporte diario y recuperación de fallos

## Nota de ingeniería

El objetivo de este repositorio no es “hacerlo bonito” sin validar el sistema real, sino dejar una base funcional y honesta para construir la beta con evidencia real. Por eso la documentación prioriza claridad sobre la arquitectura actual, riesgos conocidos y próximos pasos operativos.

## Licencia

Este proyecto se distribuye para uso interno de desarrollo y validación del prototipo hasta que la fase beta quede estabilizada.
