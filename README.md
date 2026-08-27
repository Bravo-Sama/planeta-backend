# 🪐 Proyecto Planeta - Motor IA para Aguas Décimas

Planeta es una arquitectura modular de Inteligencia Artificial (basada en RAG - Retrieval-Augmented Generation) desarrollada para procesar, almacenar y consultar documentación técnica y normativas de servicios sanitarios.

## 🚀 Arquitectura y Tecnologías

El sistema está completamente contenerizado y dividido en "satélites" (módulos) independientes que orbitan un núcleo central:

* **Core Backend:** Django (Python)
* **Bases de Datos:** 
  * MariaDB (Datos relacionales)
  * Qdrant (Base de datos espacial/vectorial)
* **Caché y Colas:** Redis + Celery
* **Motor de IA (Local):** Ollama
  * *Embeddings:* `nomic-embed-text`
  * *Generación (LLM):* `llama3`
* **Orquestación:** Docker & Docker Compose
* **Automatización:** n8n (Fase de integración)

## 📂 Estructura de Satélites (Módulos)

* **`planeta_project/`**: El núcleo de configuración de Django.
* **`satelite_limpiador/`**: Módulo encargado de la ingesta de documentos. Extrae texto puro de archivos PDF (usando PyMuPDF) mediante una interfaz web, blindando la entrada de datos.
* **`rag_engine/`**: El cerebro del sistema. Fragmenta el texto (chunking), lo traduce a vectores matemáticos y realiza búsquedas semánticas en Qdrant para alimentar al LLM.
* **`api_central/`**: (En desarrollo) Puente de comunicación RESTful que conectará las consultas del exterior (n8n/Telegram) con el motor interno.

## 🛠️ Instalación y Despliegue

1. **Clonar el repositorio:**
   ```bash
   git clone [https://github.com/Bravo-Sama/planeta-backend.git](https://github.com/Bravo-Sama/planeta-backend.git)
   cd planeta-backend
