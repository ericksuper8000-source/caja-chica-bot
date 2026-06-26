# El Analista Financiero de Caja Chica v赤a WhatsApp ??????

Bot privado de automatizaci車n, captura y control financiero dise?ado para micro-PYMEs en Costa Rica.  
El sistema permite registrar de forma estructurada ingresos y gastos mediante el procesamiento as赤ncrono de notas de voz y mensajes de texto enviados por WhatsApp, traduciendo modismos locales a datos contables exactos.

Este repositorio refleja un enfoque de ingenier赤a profesional junior:  
**Spec-Driven Development (SDD)**, **Test-Driven Development (TDD)**, automatizaci車n estricta de infraestructura (CI/CD) y aislamiento de datos multitenant.

---

## ?? Arquitectura y Decisiones T谷cnicas Basadas en Datos

El sistema sigue un patr車n de microservicios contenerizados y as赤ncronos para garantizar alta disponibilidad y cumplir con las restricciones de negocio:

- **Backend API:** Python 3.12 + FastAPI. Elegido por su velocidad nativa y validaci車n autom芍tica en tiempo de ejecuci車n con Pydantic.
- **Procesamiento As赤ncrono (Celery + Redis):** **Decisi車n Cr赤tica de Ingenier赤a.** Meta exige que el webhook de WhatsApp responda con un HTTP 200 OK en menos de 2 segundos.  
  Operaciones pesadas como descargar el audio de Meta, transcribirlo con OpenAI Whisper y procesarlo con GPT-4o-mini toman m芍s de 2 segundos.  
  Celery delega estas tareas a segundo plano, garantizando respuestas inmediatas a la API de Meta.
- **Base de Datos:** PostgreSQL 15+ para auditor赤a, persistencia de logs y preparaci車n de aislamiento de datos (*Data Isolation*).
- **APIs de IA:** OpenAI Whisper API para la transcripci車n adaptada al contexto tico y GPT-4o-mini utilizando *Structured Outputs* para asegurar que el JSON extra赤do se acople perfectamente a los esquemas de Pydantic sin mutaciones inesperadas.
- **Proxy Inverso:** Caddy Server para el manejo automatizado y nativo de certificados SSL (HTTPS obligatorio por los requerimientos de seguridad de Meta).

---

## ??? Estado del Proyecto y L赤nea de Tiempo (Checklist Ejecutado)

El desarrollo se ejecuta bajo una metodolog赤a estrictamente secuencial, donde ninguna feature avanza si la suite de pruebas unitarias no est芍 en verde.

### ?? Semana 1: Infraestructura y Handshake con Meta (Completado)
- [x] **Fase 0: Entorno Base:** Arquitectura multi-stage en Docker Compose, sincronizaci車n cruzada de pipelines en GitHub/GitLab, pol赤ticas de ramas (`main` protegida, desarrollo en `develop`).
- [x] **Pasos 1.1 a 1.3: Capa de Seguridad:** Endpoint `GET` para resolver el desaf赤o `hub.challenge` de Meta y endpoint `POST` integrado con esquemas Pydantic.
- [x] **Escudo Criptogr芍fico:** Verificaci車n de firmas HMAC-SHA256 (`X-Hub-Signature-256`) nativa en `app/core/security.py`.

### ?? Semana 2: Asincron赤a, IA y Suite "Test Tico" (Completado)
- [x] **Paso 2.1 a 2.3: Orquestaci車n As赤ncrona:** Configuraci車n de instancias de Celery con Redis e implementaci車n de la tarea distribuida `download_audio_task`.
- [x] **Paso 2.4 y 2.5: Integraci車n de IA:** Desarrollo del wrapper as赤ncrono para Whisper y el extractor financiero estructurado con GPT-4o-mini.
- [x] **Paso 2.6: Suite de Pruebas "Test Tico":** Implementaci車n de 18 pruebas unitarias que eval迆an el parseo correcto de modismos contables costarricenses (Ej: "3 rojos" ? 3000, "un tuc芍n" ? 5000).

### ?? Pr車xima Etapa: Persistencia y Notificaci車n de Retorno (En Progreso)
- [ ] **Fase 3:** Configuraci車n de autenticaci車n con Google Cloud Platform, inyecci車n at車mica de datos v赤a `gspread` e integraci車n del flujo s赤ncrono de celdas dentro del entorno as赤ncrono.

---

## ?? Calidad de C車digo e Integraci車n Continua (CI/CD)

Este repositorio implementa pipelines automatizados id谷nticos tanto en **GitHub Actions** (`.github/workflows/ci.yml`) como en **GitLab CI/CD** (`.gitlab-ci.yml`).  
El pipeline act迆a como un guardrail bloqueante para proteger la rama `main` de regresiones:

1. **Black:** Formateador estricto para estilo homog谷neo.
2. **Ruff:** Linter de alto rendimiento para interceptar c車digo muerto y malas pr芍cticas.
3. **Mypy (--strict):** Validaci車n estricta de Type Hints.
4. **Pytest (Suite As赤ncrona):** Pruebas unitarias con `pytest-asyncio`.

### ?? Verificaci車n Local Preventiva
```bash
# Formatear y verificar estilo est芍tico
black --check app/ workers/ services/ tests/

# Analizar con el linter ruff
ruff check app/ workers/ services/ tests/

# Validar tipado estricto
mypy --strict app/

# Correr la suite de pruebas completa
pytest tests/


## ?? Inicializaci車n del Entorno de Desarrollo

# 1. Clonar el repositorio
git clone https://github.com/ericksuper8000-source/caja-chica-bot.git
cd caja-chica-bot

# 2. Inicializar variables de entorno locales
cp .env.example .env

# 3. Levantar la infraestructura completa en segundo plano
docker compose up -d

# 4. Verificar salud operacional de los contenedores
docker compose ps


### ?? Roadmap y Mejoras Futuras (Mentalidad de Escalamiento)

Desacoplamiento de la Inicializaci車n Global (Lazy Loading): Migrar el cliente de OpenAI a inicializaci車n perezosa o inyecci車n de dependencias por funci車n.

Aislamiento Multitenant por Base de Datos: Mapear din芍micamente tenant_id derivado del n迆mero de WhatsApp para aislar transacciones en PostgreSQL.

Optimizaci車n As赤ncrona de I/O en Google Sheets: Encapsular la capa del conector en Thread Pools o migrar hacia un backend as赤ncrono nativo.