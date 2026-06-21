# El Analista Financiero de Caja Chica vía WhatsApp 🇨🇷🤖

Bot privado de automatización y control financiero diseñado para micro-PYMEs en Costa Rica. El sistema permite registrar de forma estructurada ingresos y gastos mediante el procesamiento asíncrono de notas de voz y mensajes de texto enviados por WhatsApp.

## 🚀 Arquitectura y Stack Tecnológico

El proyecto sigue un patrón de microservicios contenerizados y asíncronos para cumplir de forma estricta con las restricciones de tiempo de respuesta de la API de WhatsApp de Meta:

- **Backend API:** Python 3.12 + FastAPI (Manejo de Webhooks de alta velocidad)
- **Procesamiento Asíncrono:** Celery Task Queue
- **Message Broker & Cache:** Redis
- **Base de Datos:** PostgreSQL 15+ (Auditoría, logs y data isolation)
- **Estrategia de Despliegue:** Contenedores aislados mediante Docker & Docker Compose

---

## 🛠️ Estado del Proyecto e Infraestructura Local

Actualmente, el proyecto se encuentra en desarrollo activo de su MVP. La infraestructura base local está completamente configurada y validada:

- [x] Arquitectura de contenedores multi-stage (Docker)
- [x] Orquestación de servicios en red local (FastAPI, Worker, Redis, DB)
- [x] Sincronización e integración de repositorios remotos simultáneos (GitHub/GitLab)
- [x] Políticas de protección de ramas en la nube (`main` protegida, desarrollo sobre `develop`)

---

## 💻 Inicialización del Entorno de Desarrollo

Para levantar el entorno local de forma contenerizada, asegúrese de tener Docker Desktop activo y ejecute:

```bash
# Clonar y acceder al directorio
cd caja-chica-bot

# Levantar los 4 servicios en segundo plano
docker compose up -d

# Verificar el estado de los contenedores
docker compose ps


⚙️ Integración Continua (CI/CD) y Calidad de Código
Este proyecto implementa pipelines de automatización tanto en GitHub Actions como en GitLab CI/CD para garantizar la estabilidad, el formato y la consistencia del código en cada commit o Pull Request.

El flujo de trabajo ejecuta de manera secuencial las siguientes herramientas de análisis estático:

Black: Formateador de código estricto para asegurar un estilo homogéneo.

Ruff: Linter de alto rendimiento para identificar errores, código muerto y malas prácticas.

Mypy (--strict): Validador de tipado estático para asegurar la integridad de los tipos en la aplicación.

🧪 Verificación Local
Para asegurar que los pipelines pasen exitosamente antes de hacer un push, se pueden ejecutar los mismos comandos localmente en el entorno virtual:

Bash
# 1. Formatear y verificar estilo
black --check app/ workers/ services/ tests/

# 2. Analizar el código con el linter
ruff check app/ workers/ services/ tests/

# 3. Validar el tipado estático estrictamente
mypy --strict app/