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
