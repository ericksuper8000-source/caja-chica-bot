# El Analista Financiero de Caja Chica via WhatsApp PONYO

Bot privado de automatizacion, captura y control financiero disenado para micro-PYMEs en Costa Rica. El sistema permite registrar de forma estructurada ingresos y gastos mediante el procesamiento asincrono de notas de voz y mensajes de texto enviados por WhatsApp, traduciendo modismos locales ("rojos", "tucanes", "tejas") a datos contables exactos y persistiendo la informacion de forma inmediata.

Este repositorio refleja un enfoque de ingenieria profesional con mentalidad de escalamiento: **Spec-Driven Development (SDD)**, **Test-Driven Development (TDD)**, analisis estatico estricto y automatizacion de infraestructura reflejada en pipelines de CI/CD espejados.

---

## ??? Arquitectura y Decisiones Tecnicas Basadas en Datos

El sistema sigue un patron de microservicios contenerizados y asincronos para garantizar alta disponibilidad y cumplir con las restricciones de negocio:

* **Backend API:** Python 3.12 + FastAPI. Elegido por su velocidad nativa y validacion automatica en tiempo de ejecucion con Pydantic v2.
* **Procesamiento Asincrono (Celery + Redis):** **Decision Critica de Ingenieria.** Meta exige que el webhook de WhatsApp responda con un HTTP 200 OK en menos de 2 segundos. Operaciones pesadas como descargar el audio de Meta, transcribirlo con OpenAI Whisper y procesarlo con GPT-4o-mini toman mas de 2 segundos. Celery delega estas tareas a segundo plano, garantizando respuestas inmediatas a la API de Meta.
* **Base de Datos:** PostgreSQL 15+ para auditoria, persistencia de logs y preparacion de aislamiento de datos (*Data Isolation*).
* **APIs de IA:** OpenAI Whisper API para la transcripcion adaptada al contexto tico y GPT-4o-mini utilizando *Structured Outputs* para asegurar que el JSON extraido se acople perfectamente a los esquemas de Pydantic sin mutaciones inesperadas.
* **Capa de Persistencia Externa (Fase 3):** Conexion fisica asincrona hacia Google Sheets mediante la inyeccion atomica de datos estructurados con `gspread` y `google-auth`.
* **Proxy Inverso:** Caddy Server para el manejo automatizado y nativo de certificados SSL (HTTPS obligatorio por los requerimientos de seguridad de Meta).

---

## ??? Estado del Proyecto y Linea de Tiempo (Checklist Ejecutado)

El desarrollo se ejecuta bajo una metodologia estrictamente secuencial (TDD), donde ninguna feature avanza si la suite de pruebas unitarias no esta en verde.

### ?? Semana 1: Infraestructura y Handshake con Meta *(Tiempo estimado: 12h / Real: 14h)*
- [x] **Fase 0: Entorno Base:** Arquitectura multi-stage en Docker Compose, sincronizacion cruzada de pipelines en GitHub/GitLab, politicas de ramas (`main` protegida, desarrollo en `develop`).
- [x] **Pasos 1.1 a 1.3: Capa de Seguridad:** Endpoint `GET` para resolver el desafio `hub.challenge` de Meta y endpoint `POST` integrado con esquemas Pydantic.
- [x] **Escudo Criptografico:** Verificacion de firmas HMAC-SHA256 (`X-Hub-Signature-256`) nativa en `app/core/security.py`.

### ?? Semana 2: Asincronia, IA y Suite "Test Tico" *(Tiempo estimado: 16h / Real: 15h)*
- [x] **Paso 2.1 a 2.3: Orquestacion Asincrona:** Configuracion de instancias de Celery con Redis e implementacion de la tarea distribuida `download_audio_task`.
- [x] **Paso 2.4 y 2.5: Integracion de IA:** Desarrollo del wrapper asoncronico para Whisper y el extractor financiero estructurado con GPT-4o-mini.
- [x] **Paso 2.6: Suite de Pruebas "Test Tico":** Implementacion de 18 pruebas unitarias que evaluan el parseo correcto de modismos contables costarricenses (Ej: "3 rojos" ? 3000, "un tucan" ? 5000).

### ?? Semana 3: Persistencia Fisica en Hojas de Calculo *(Tiempo estimado: 10h / Real: 12h)*
- [x] **Paso 3.1: Autenticacion GCP:** Integracion segura con Google Cloud Platform utilizando cuentas de servicio de manera hermetica a traves de variables de entorno.
- [x] **Paso 3.2: Pipeline de Inyeccion Fisica:** Implementacion del servicio persistente `sheets_service.py` encargado de dar formato, mapear campos e insertar registros de forma atomica.
- [x] **Paso 3.3: Orquestacion Celery-Sheets:** Encapsulamiento del pipeline de Sheets dentro de los workers asincronos distribuidos en `workers/tasks.py`.
- [x] **Paso 3.4: Robustez CI/CD Multicloud:** Modificacion de la inicializacion de configuraciones globales para superar la verificacion estricta de Linters (`mypy --strict`, `black`, `ruff`) y Pytest en entornos virtuales aislados.

---

## ?? Tiempos de Implementacion y Estimados

| Fase / Funcionalidad | Esfuerzo Estimado | Esfuerzo Real | Estado |
| :--- | :---: | :---: | :---: |
| **Fase 0:** Configuracion Docker & CI/CD Espejo | 4 horas | 5 horas | Completado |
| **Fase 1:** Seguridad Webhook & Validacion HMAC | 8 horas | 9 horas | Completado |
| **Fase 2:** Orquestacion Celery + Modelos de IA | 16 horas | 15 horas | Completado |
| **Fase 3:** Integracion Fisica con Google Sheets y Refactor de Tipado en CI | 10 horas | 12 horas | Completado |
| **Fase 4:** OpenAI Assistant Integration & Respuestas Dinamicas WhatsApp | 14 horas | *Por ejecutar* | Pendiente |

---

## ?? Nuevas Funcionalidades Agregadas (Detalle Tecnico Fase 3)

### Pipeline Asincrono de Persistencia en Google Sheets
Se ha acoplado un canal de persistencia que extrae los datos JSON estructurados por los LLMs y los transforma de inmediato en filas ordenadas dentro de una hoja de calculo remota.
* **Inicializacion Segura con Fallbacks:** La clase de configuraciones centrales (`app/config.py`) fue blindada utilizando `Field(default="")` de Pydantic v2. Esto permite que la aplicacion se auto-instancie de manera segura en entornos de compilacion de CI/CD (GitHub Actions y GitLab) donde las llaves de produccion no estan pobladas, evitando interrupciones catastroficas en el parseo de pruebas locales.
* **Cumplimiento Estricto de Mypy:** Se reestructuro la declaracion de tipos de Pydantic Settings para satisfacer el tipado estricto (`--strict`), eliminando advertencias de argumentos perdidos en constructores mediante la asignacion explicita de valores por defecto tipados.

---

## ?? Retrospectiva: ?Que hariamos distinto en un Rediseno?

Si tuvieramos que reconstruir esta capa de persistencia desde cero, implementariamos las siguientes mejoras arquitectonicas:

1.  **Eliminacion Completa de Dependencias Sincronas (gspread):** La libreria `gspread` realiza llamadas bloqueantes de I/O por debajo. En un entorno de alto trafico, aunque este delegado a un worker de Celery, bloquea el hilo del worker. Reemplazariamos esto utilizando la API REST nativa de Google de forma asincrona mediante `httpx` o integrando `aiogspread`.
2.  **Plugin de Mypy para Pydantic Nativo:** Para evitar tener que llenar la clase `Settings` con campos por defecto vacios (`default=""`), se configuraria un archivo `mypy.ini` estricto que cargue explicitamente el plugin de Pydantic (`plugins = pydantic.mypy`). Esto permitiria mantener los atributos de variables de entorno como estrictamente requeridos sin disparar errores falsos positivos en el analizador estatico durante el analisis del constructor.

---

## ??? Calidad de Codigo e Integracion Continua (CI/CD)

Este repositorio implementa pipelines automatizados identicos tanto en **GitHub Actions** (`.github/workflows/ci.yml`) como en **GitLab CI/CD** (`.gitlab-ci.yml`). El pipeline actua como un guardrail bloqueante para proteger las ramas principales de regresiones:

1.  **Black:** Formateador estricto para estilo homogeneo.
2.  **Ruff:** Linter de alto rendimiento para interceptar codigo muerto y malas practicas.
3.  **Mypy (--strict):** Validacion estricta de Type Hints sobre todo el ecosistema de configuraciones.
4.  **Pytest (Suite Asincrona):** 18 pruebas unitarias validadas que corren de manera automatizada en cada push remoto.

### ??? Verificacion Local Preventiva
Ejecuta estos comandos en tu terminal local antes de realizar un push para garantizar la aceptacion del pipeline en la nube:

```bash
# Formatear y verificar estilo estatico completo
black --check app/ workers/ services/ tests/

# Analizar y auto-corregir con el linter ruff
ruff check app/ workers/ services/ tests/ --fix

# Validar tipado estricto
mypy --strict app/

# Correr la suite de pruebas completa
pytest tests/
