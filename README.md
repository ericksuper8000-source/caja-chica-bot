# 🤖 El Analista Financiero de Caja Chica vía WhatsApp
**Fecha de inicio:** 10/07/2026  
**Tipo:** Bot privado de automatización, captura y control financiero para micro-PYMEs en Costa Rica.

El sistema permite registrar ingresos y gastos mediante procesamiento asincrónico de notas de voz y mensajes de texto enviados por WhatsApp, traduciendo modismos locales ("rojos", "tucanes", "tejas") a datos contables exactos y persistiendo la información de forma inmediata.

---

## 🏗️ Arquitectura y Decisiones Técnicas Basadas en Datos
El sistema sigue un patrón de **microservicios contenerizados y asincrónicos** para garantizar alta disponibilidad y cumplir con las restricciones de negocio:

- **Backend API:** Python 3.12 + FastAPI (validación automática con Pydantic v2).
- **Procesamiento Asincrónico:** Celery + Redis. Respuesta inmediata al webhook de WhatsApp (<2s).
- **Base de Datos:** PostgreSQL 15+ (auditoría y aislamiento de datos).
- **APIs de IA:** OpenAI Whisper API + GPT-4o-mini con Structured Outputs.
- **Persistencia Externa (Fase 3):** Google Sheets vía gspread + google-auth.
- **Proxy Inverso:** Caddy Server (SSL nativo y automatizado).

---

## 📌 Estado del Proyecto y Línea de Tiempo
Metodología: **TDD estricto** (ninguna feature avanza si las pruebas no están en verde).

### 📅 Semana 1: Infraestructura y Handshake con Meta
- [x] Fase 0: Entorno Base (Docker Compose, CI/CD espejado, ramas protegidas).
- [x] Endpoints GET/POST con Pydantic.
- [x] Verificación HMAC-SHA256 en `app/core/security.py`.

### 📅 Semana 2: Asincronía, IA y Suite "Test Tico"
- [x] Configuración Celery + Redis (`download_audio_task`).
- [x] Wrapper asincrónico para Whisper + extractor financiero con GPT-4o-mini.
- [x] Suite de 23 pruebas unitarias para modismos contables costarricenses.

### 📅 Semana 3: Persistencia Física, Saneamiento y Validación
- [x] Autenticación GCP (incl. gestión segura de secretos).
- [x] Servicio `sheets_service.py` y orquestación Celery-Sheets.
- [x] Normalización de paquetes (`__init__.py`).
- [x] **Validación de Calidad Local:** Implementación de `black`, `flake8` (configuración personalizada) y validación de suite de 23 pruebas unitarias.

---

## 🛡️ Seguridad y Endurecimiento (Hardened)
- **Gestión de Secretos:** Implementación de blindaje de credenciales mediante `pydantic-settings` y variables de entorno. 
- **Aislamiento de Seguridad:** Eliminación de archivos JSON de credenciales del VCS (Git) y configuración de `.gitignore` estricto para evitar filtraciones.

---

## ⏱️ Tiempos de Implementación
| Fase | Estimado | Real | Estado |
|------|----------|------|--------|
| Configuración Docker & CI/CD | 4h | 5h | ✅ Completado |
| Seguridad Webhook & HMAC | 8h | 9h | ✅ Completado |
| Orquestación Celery + IA | 16h | 15h | ✅ Completado |
| Integración Sheets & Refactor | 10h | 14h | ✅ Completado |
| Validación de Calidad y Estilo | 2h | 3h | ✅ Completado |
| OpenAI Assistant Integration | 14h | - | ⏳ Pendiente |

---

## 🔄 Retrospectiva: ¿Qué haríamos distinto?
- Sustituir **gspread** por API REST nativa de Google (asincronía con `httpx`).
- Configurar `mypy.ini` con plugin `pydantic.mypy`.

---

## ✅ Calidad de Código y CI/CD
Pipelines idénticos en GitHub Actions y GitLab CI/CD con:
- **Black:** Formateador estricto aplicado.
- **Flake8:** Linter configurado con `max-line-length = 100`.
- **Mypy (--strict):** Validación estricta de Type Hints.
- **Pytest:** 23 pruebas unitarias validadas (suite asincrónica).