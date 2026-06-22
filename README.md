# El Analista Financiero de Caja Chica vía WhatsApp 🇨🇷🤖

Bot privado de automatización y control financiero diseñado para micro-PYMEs en Costa Rica. El sistema permite registrar de forma estructurada ingresos y gastos mediante el procesamiento asíncrono de notas de voz y mensajes de texto enviados por WhatsApp.

## 🚀 Arquitectura y Stack Tecnológico

El proyecto sigue un patrón de microservicios contenerizados y asíncronos para cumplir de forma estricta con las restricciones de tiempo de respuesta de la API de WhatsApp de Meta:

- **Backend API:** Python 3.12 + FastAPI (Manejo de Webhooks de alta velocidad)
- **Procesamiento Asíncrono:** Celery Task Queue
- **Message Broker & Cache:** Redis
- **Base de Datos:** PostgreSQL 15+ (Auditoría, logs y data isolation)
- **APIs de IA:** OpenAI Whisper API (Transcripción) + GPT-4o-mini (Extracción Estructurada)
- **Estrategia de Despliegue:** Contenedores aislados mediante Docker & Docker Compose
- **Proxy Inverso:** Caddy Server (SSL Automático)

---

## 🛠️ Estado del Proyecto e Infraestructura Local

El proyecto se encuentra en desarrollo activo de su MVP. Hemos consolidado la infraestructura base y la capa de comunicación y seguridad inicial con Meta:

- [x] **Fase 0: Infraestructura Base Local:** Arquitectura de contenedores multi-stage (FastAPI, Worker, Redis, DB), sincronización de repositorios remotos simultáneos (GitHub/GitLab), políticas de ramas (`main` protegida, desarrollo en `develop`) y pipelines de CI (Black, Ruff, Mypy).
- [x] **Paso 1.1: Handshake con Meta:** Endpoint `GET /v1/whatsapp/webhook` completamente funcional para resolver el desafío `hub.challenge`.
- [x] **Paso 1.2: Validación de Payload:** Endpoint `POST /v1/whatsapp/webhook` integrado con modelos de validación Pydantic (`WebhookPayload`).
- [x] **Paso 1.3: Escudo Criptográfico:** Verificación robusta de firmas HMAC-SHA256 (`X-Hub-Signature-256`) implementada de forma nativa en `app/core/security.py` para bloquear orígenes no legítimos.

---

## 💻 Inicialización del Entorno de Desarrollo

Para levantar el entorno local de forma contenerizada, asegúrese de tener Docker Desktop activo y ejecute:

```bash
# 1. Clonar y acceder al directorio del proyecto
cd caja-chica-bot

# 2. Inicializar tus secretos locales a partir de la plantilla
cp .env.example .env

# 3. Levantar los 4 servicios en segundo plano
docker compose up -d

# 4. Verificar el estado operativo de los contenedores
docker compose ps

⚙️ Integración Continua (CI/CD) y Calidad de Código
Este proyecto implementa pipelines de automatización idénticos tanto en GitHub Actions como en GitLab CI/CD para garantizar la estabilidad, el formato y la consistencia estricta del tipado en cada commit o Pull Request.

El flujo de trabajo ejecuta de manera secuencial las siguientes herramientas de análisis estático:

Black: Formateador estricto para un estilo de código homogéneo.

Ruff: Linter de alto rendimiento para identificar errores y código muerto.

Mypy (--strict): Validador de tipado estático obligatorio para mitigar errores en tiempo de ejecución.

🧪 Verificación Local
Para asegurar que los pipelines pasen exitosamente antes de hacer un push a develop, se pueden ejecutar los mismos comandos localmente en el entorno virtual o contenedor:

Bash
# 1. Formatear y verificar estilo
black --check app/ workers/ services/ tests/

# 2. Analizar el código con el linter ruff
ruff check app/ workers/ services/ tests/

# 3. Validar el tipado estático estrictamente
mypy --strict app/