# El Analista Financiero de Caja Chica vía WhatsApp

**Inicio:** 10/07/2026 · **Última actualización:** 12/08/2026  
**Tipo:** Bot privado de automatización, captura y control financiero para micro-PYMEs en Costa Rica.

Registra ingresos y gastos mediante notas de voz y mensajes de texto enviados por WhatsApp. Traduce modismos ticos ("rojos", "tucanes", "tejas") a datos contables exactos usando IA, y persiste la información en Google Sheets.

---

## Features

### Core
- **Webhook Meta WhatsApp** — Endpoints GET/POST `/v1/whatsapp/webhook` con verificación HMAC-SHA256 y payload tipado (7 modelos Pydantic anidados con `model_dump(by_alias=True)`, `AudioMedia`, `Message`, `Contact`, `Value`, `Change`, `Entry`, `WebhookPayload`).
- **Transcripción Whisper API** — Procesamiento asíncrono de audio vía OpenAI Whisper.
- **Extracción Financiera con GPT-4o-mini** — Structured Outputs para extraer `monto` (int), `categoria`, `tipo_movimiento`, `detalle` desde lenguaje natural y modismos costarricenses.
- **Persistencia en Google Sheets** — Inyección atómica vía `gspread` + `asyncio.to_thread`.
- **Notificación Outbound** — Respuesta automática al usuario por WhatsApp tras cada transacción exitosa o fallida.

### Estabilización y Hardening (29/07/2026)
- **Rate Limiting** — slowapi middleware (`10/min` producción, `1000/min` test) protege contra abuso de API de OpenAI. Responde HTTP 429 al exceder el límite.
- **Health Check** — `GET /health` verifica conectividad con Redis y Celery (200 ok / 503 degraded).
- **Caché de Clientes** — `gspread` client y `httpx.AsyncClient` se inicializan una sola vez (`lru_cache` y variable de módulo respectivamente).
- **Manejo de Errores al Usuario** — Cuando Whisper no transcribe o el parser no entiende, el bot responde por WhatsApp con un mensaje de cortesía en lugar de fallar silenciosamente.
- **Pipeline Asíncrono Limpio** — Las 3 operaciones (Whisper → GPT → Sheets + WhatsApp) se ejecutan en un solo `asyncio.run()` mediante `_procesar_pipeline()`, eliminando la creación de 3-4 event loops por tarea.
- **Archivos Temporales Seguros** — Uso de `tempfile.gettempdir()` en lugar de `/tmp` hardcodeado; `os.remove()` protegido con `try/except OSError`.
- **Validación de Argumentos** — `extraer_datos_audio()` lanza `ValueError` si `media_id` o `from_phone` son `None`.
- **Tipado** — Mypy (config `pyproject.toml`, sin `--strict`, igual que la CI) en verde
  sobre 15 archivos fuente. Schemas con Pydantic v2.

### Corrección de Autenticación Meta (03/08/2026)
- **Bearer Token en descarga de audio (3.8.1)** — `workers/tasks.py` envía `Authorization: Bearer` en las dos llamadas a Meta (info del media y descarga del archivo). Antes la descarga fallaba con `401 Unauthorized`. Test en `tests/test_tasks.py` verifica que ambas llamadas incluyen el header.
- **Validación de descarga 200 OK (3.8.2, a medias)** — Prueba directa contra servidores reales de Meta: subir nota de voz real → media_id → descargar con el fix respondió `200 OK` (archivo idéntico, 66.977 bytes).

### Verificación de Meta completada (05/08/2026)
- **App Secret real aplicado** — El `.env` usaba un placeholder (`mi_clave_secreta_de_meta_super_segura`); el real (`***REDACTED_APP_SECRET***`, de Meta → Configuración → Básico) quedó configurado y el contenedor recreado (`docker compose up -d app`; un `restart` no basta).
- **Firma HMAC-SHA256 validada matemáticamente** — El secret correcto reproduce la firma de Meta (`sha256=95ebcdd...`); el POST local con firma válida responde `200 {"status":"recibido"}` (el 403 desapareció).
- **Suscripción WABA→App exitosa** — `POST /v26.0/<WABA>/subscribed_apps` → `{"success":true}`.
- **Handshake de Meta** — `GET /v1/whatsapp/webhook` con `hub.challenge` responde 200.
- **Pipeline de IA demostrado de punta a punta SIN Meta** — Con un audio real (`Almuerzo.m4a`): Whisper transcribió *"Se gastaron 2.500 colones en el almuerzo."*; GPT-4o-mini extrajo `{monto:2500, categoria:Alimentación, tipo:Gasto, detalle:Almuerzo}`; Google Sheets registró la fila `-2500 | Alimentación | Almuerzo` (verificada leyendo la hoja de vuelta).
- **Nota de audio `.m4a`:** Whisper rechaza el codec AAC de los `.m4a` de iPhone ("Invalid file format"); convertirlos a WAV 16 kHz mono lo resuelve. Los `.ogg` (OPUS) de WhatsApp no tienen este problema.

### E2E real completado (06/08/2026)
- **El "bloqueo por verificación de empresa" era un FALSO POSITIVO:** la causa real de que
  los audios no llegaran era el **callback URL del webhook borrado/no vigente** en la
  suscripción de la app. Se re-registró vía API (`POST /v26.0/{app_id}/subscriptions` con
  `callback_url=https://outweigh-reuse-blouse.ngrok-free.dev/v1/whatsapp/webhook`,
  `verify_token` y `fields=messages`) → `{"success":true}` y handshake de Meta → 200 OK.
- **Pipeline E2E real probado con una nota de voz:** WhatsApp → Meta → ngrok → FastAPI →
  Celery → Whisper → GPT-4o-mini → Google Sheets → respuesta en WhatsApp:
  **"Transacción registrada: Alimentación - 3000 colones"** (3 POSTs de Meta al webhook,
  todos 200 `{"status":"recibido"}`).
- **Limitante actual (PUNTO A, no vendible):** la app sigue en **Development mode** y el
  número es de prueba (EEUU +1 555). El bot responde solo a **hasta 5 destinatarios** en la
  allowlist del sandbox; los entrantes llegan de cualquier número. El modo dev SÍ entrega
  tráfico real mientras el destinatario esté en la allowlist. Para producción (PUNTO B) se
  necesita número real registrado en la WABA + despliegue HTTPS (5.1) — ver
  `execution-plan.md` §"MAPA DE LISTO PARA".

### Precisión de la IA medible (Fase 5.5, 10/08/2026)
- **Conjunto dorado (`specs/golden_set.json`)** — 34 casos con frase transcripción esperada y
  respuesta correcta (monto/categoría/tipo), incluyendo modismos ticos, montos en palabras,
  casos sin monto, audio largo, ruido de fondo y **casos de corrección (31–34)**.
- **Audios reales (`specs/golden_audio/`)** — 33 audios grabados por el fundador
  (`Caso_2.m4a`…`Caso_34.m4a`); el Caso 1 fue validado aparte por el E2E real. Los casos
  27–30 son propios del dueño (dos flujos en un audio / ruido de fondo).
- **Eval automatizado (`specs/eval_precision.py`)** — corre Whisper + GPT-4o-mini sobre el
  conjunto dorado y reporta % de acierto en monto/categoría/tipo contra lo esperado.
  **Resultado (10/08/2026): monto ≥96.2%, categoría ≥96.2%, tipo 100%** en el peor escenario
  de 3 corridas (meta ≥95%).
- **Prompt afinado (`services/openai_service.py`, `parse_financial_text`)** — montos SIEMPRE
  en colones ignorando símbolos (`$3,000` = 3000) y lista fija de categorías con mapeo de
  sinónimos (inventario/mercadería/equipo → Compras; pago a empleado → Personal; entrante
  por ventas → Ventas). Redujo categoría 57.7% → ≥96.2% sin cambiar de modelo.
- **Guía de grabación (`specs/guia-grabacion.md`)** — cómo grabar nuevos casos, nombres de
  archivo y grilla.
- **Nota `.m4a` (confirmado de nuevo):** Whisper rechaza el codec AAC de las grabadoras de
  celular; se convierte a WAV 16 kHz mono con ffmpeg (instalado en el contenedor, se pierde
  al recrearlo) antes de evaluar.

### Flujo de corrección y aclaración por WhatsApp (Fase 5.5.3, 11/08/2026)
- **Columna "teléfono" en la hoja** — `append_transaction_to_sheet` guarda el número del
  remitente (columna E) para saber **cuál fila corregir** (la última de ESE usuario) y
  prepara el terreno para 6.1 (identidad por teléfono) y 6.5 (aislamiento por pestañas).
- **Intención detectada por la IA** — `TransactionResponse` ahora tiene `accion`:
  `registrar` / `corregir` / `aclaracion`. El system prompt distingue una corrección
  ("era X no Y"), un registro normal y un mensaje con dos flujos.
- **Corrección real (ADR-0010)** — "corrige, eran 6 rojos no 5" → `update_last_transaction_to_sheet`
  localiza la última fila del remitente y la fusiona con el **delta** corregido
  (semántica delta: campo `null` = conservar el valor anterior; solo aplica lo que el usuario
  menciona). Reescribe monto/categoría/tipo/detalle conservando la fecha; el bot confirma
  "Corregido: ₡6000 en Alimentación". NO crea una transacción nueva.
- **Pedido de aclaración** — si el mensaje trae dos flujos (ingreso + gasto, o dos montos),
  el bot NO registra nada y responde "Vi dos movimientos... ¿cuál querés que apunte?"
  (caso 27: ✅ verificado en eval).
- **Eval ampliado** — `golden_set.json` v5 + casos 31–34 (corrección) con sus audios;
  `eval_precision.py` reporta `accion` y comportamiento. Corrida 11/08/2026: monto 29/30 =
  96.7% (meta alcanzada), correcciones 31–34 reconocen `corregir`, caso 27 `PIDE_ACLARACION`.
  Quedan para 5.5.4: casos 6, 11/20, 22 y correcciones parciales 32/34 (categoria/tipo en null).
  → **Resueltos el 12/08/2026 (ver Fase 5.5.4 abajo).**
- **Validado E2E real en WhatsApp (11/08/2026)** — con 2 notas de voz reales, la 2ª
  ("corrige, no eran dos, eran 5") **actualizó la última fila del teléfono en vez de crear
  una nueva** → respuesta "Corregido" recibida en WhatsApp. Requisito operativo descubierto:
  tras cambiar de rama/archivos hay que **reiniciar los contenedores**
  (`docker compose restart app worker`); el volumen `.:/code` no recarga los módulos en memoria.
- **2 bugs de producción corregidos en el camino:**
  1. `tipo_movimiento: null` (GPT Structured Outputs) rompía `tipo.lower()` en Sheets →
     default `or "Gasto"` en `append_transaction_to_sheet` y `update_last_transaction_to_sheet`
     (`services/sheets_service.py`).
  2. `Event loop is closed` al enviar la 2ª respuesta de WhatsApp: el `httpx.AsyncClient`
     global se ataba al event loop de la 1ª tarea (que `asyncio.run()` cierra al terminar).
     Solución: cliente creado **por llamada** (`async with httpx.AsyncClient()`) en
     `services/whatsapp_service.py`.
- **QA verificado sobre los 2 archivos** (autorizado por el dueño): pytest **39/39 passed** ·
  ruff **All checks passed** · black **2 files unchanged** · mypy **no issues in 2 source files**.
  Listos para subir al repo.

### Ajustes iterativos de precisión (Fase 5.5.4, 12/08/2026)
- **Trampas de regresión A–G (`tests/test_precision_regresion.py`)** — blindan las reglas de
  negocio decididas con el dueño:
  - **A** corrección = registro COMPLETO (nunca null) · **B** frase sin monto → NO se crea
    transacción (`aclaracion`) · **C** los modismos SIEMPRE resuelven a colones (monto nunca null
    si hay dinero) · **D** gastos de movilidad (parqueo/peaje/gasolina) = Transporte vs. ingreso
    por prestar un servicio = Servicios · **E** limitación aceptada de Whisper ("seis tejas" →
    "seis cejas"; con transcripción correcta la lógica acierta) · **F** un modismo con número ES
    un monto y anula el `aclaracion` por falta de monto ("dos tucanes" ≠ dos flujos) · **G**
    "Otros" solo como último recurso (Servicios/Ventas se prefieren).
- **`SYSTEM_PROMPT_PARSE` expuesto** — el system prompt ahora vive en
  `services/openai_service.py:54` como constante, para que las trampas verifiquen el contrato
  del prompt (TDD de prompt: si la regla se debilita, la trampa se enciende en rojo).
- **Eval real en el contenedor (3 corridas, 12/08/2026): monto 100% · categoría 100% · tipo
  100%** (peor de 3 = 100%) sobre el conjunto dorado de 34 casos / 33 audios. Meta de 5.5.2
  (≥95%) superada con holgura. Confirmados en vida real: caso 22 `SIN_CREAR`, caso 27
  `PIDE_ACLARACION`, casos 31–34 con registro COMPLETO.
- **QA: pytest 46/46 · ruff 0 · black sin cambios · mypy success (15 files).**
- **Pendiente 5.5.5:** integrar los tests de regresión a la CI; el eval real (audios + API de
  OpenAI) se mantiene como paso manual por costo de API.

---

## Arquitectura y Decisiones Técnicas

```
WhatsApp Usuario
    |
    v
Meta API → FastAPI (app/main.py)
    |       · Validar HMAC (app/core/security.py)
    |       · Validar schema Pydantic (app/schemas/whatsapp.py)
    |       · Extraer media_id y phone (app/core/utils.py)
    |       · Responder HTTP 200 OK (< 2 s)
    |
    v
Celery Worker (workers/tasks.py)
    · Descargar audio de Meta API
    · Transcribir con Whisper (services/openai_service.py)
    · Extraer datos con GPT-4o-mini (services/openai_service.py)
    · Insertar en Google Sheets (services/sheets_service.py)
    · Responder al usuario (services/whatsapp_service.py)
```

### Stack
| Componente | Elección | Razón |
|---|---|---|
| Backend | Python 3.12 + FastAPI | Tipado nativo, rendimiento, ecosistema |
| Tareas async | Celery + Redis (broker & backend) | Timeouts de Meta (< 2 s) exigen delegación |
| Base de datos | PostgreSQL 15+ | Auditoría y multi-tenancy futuro (no usado en MVP) |
| IA | OpenAI Whisper + GPT-4o-mini | Único provider en MVP; `transcribir_audio_whisper()` es fácil de reemplazar |
| Persistencia MVP | Google Sheets vía `gspread` | 1 hoja global para 20-50 clientes |
| Proxy | Caddy | SSL automático, cero configuración |
| CI/CD | GitHub Actions + GitLab CI | Pipelines idénticos y espejados desde un solo `push` |

### Decisiones Clave

**Persistencia Google Sheets → PostgreSQL (migración gradual):**
- MVP: 1 hoja global, todos los clientes comparten la misma hoja.
- Post-MVP (venta inicial): 1 hoja con pestañas por cliente. Sin PostgreSQL.
- Crecimiento (50+ clientes): Migrar a PostgreSQL con `tenant_id`. Razón: Sheets se vuelve lenta con >50 clientes concurrentes.
- SaaS masivo: Onboarding automatizado + Stripe + Terraform.

**Provider de IA — Solo OpenAI:**
- MVP: Whisper API + GPT-4o-mini. Sin abstracción.
- Post-MVP (>500 transacciones/día): Evaluar Ollama + Whisper local. La función es pura y fácil de reemplazar.

**Rate Limiting — slowapi en lugar de PostgreSQL + límite diario:**
- Implementación middleware, sin dependency extra de base de datos.
- Límite por minuto (10 req/min) en vez de 20/día. Protege el mismo vector de abuso con menor complejidad.
- Alternativa considerada: tabla PostgreSQL con contador diario por usuario. Se descartó porque requiere migrations, conexión a DB que aún no está en el flujo crítico, y agrega latencia a cada request.

**Single Event Loop vs. Múltiples `asyncio.run()`:**
- Original: cada sub-operación (transcripción, extracción, sheets) llamaba `asyncio.run()` por separado → 3-4 event loops por tarea, los loops anidados fallan en Python ≥ 3.12.
- Solución: una función `_procesar_pipeline()` async que orquesta todo, invocada por un único `asyncio.run()`.

---

## Estado del Proyecto

- **46 tests, 46 passed** · black y ruff 0 errores · mypy (config, sin `--strict`, como en CI) en verde · `mypy --strict` en verde (05/08/2026)
- CI/CD: GitHub Actions + GitLab CI (pipelines idénticos)
- **03/08/2026:** Descarga de audio de Meta corregida (Bearer Token) y validada con `200 OK` contra servidores reales.
- **05/08/2026:** App Secret real aplicado, firma HMAC-SHA256 validada matemáticamente, suscripción WABA→App exitosa y **pipeline de IA demostrado de punta a punta sin Meta** (webhook simulado → Whisper → GPT-4o-mini → Google Sheets).
- **06/08/2026:** **E2E REAL COMPLETO** — nota de voz real → Sheets → respuesta en WhatsApp ("Transacción registrada: Alimentación - 3000 colones"). El "bloqueo por verificación de empresa" era un falso positivo (callback URL del webhook re-registrado). Alcance actual: **PUNTO A** (testeo interno, sandbox, ≤5 destinatarios).
- **10/08/2026:** **Fase 5.5 — precisión medible.** Conjunto dorado de 30 casos
  (`specs/golden_set.json` + `specs/golden_audio/` con 29 audios reales) y eval automatizado
  (`specs/eval_precision.py`). Tras afinar el system prompt, **monto ≥96.2% (meta ≥95%),
  categoría ≥96.2%, tipo 100%** (peor de 3 corridas). (El conjunto dorado creció a **34 casos /
  33 audios** el 11/08 con los casos de corrección 31–34.)
- **11/08/2026:** **Fase 5.5.3 — flujo de corrección COMPLETO (8/8 pasos) y validado E2E real
  en WhatsApp.** Columna "teléfono" en la hoja, intención `registrar/corregir/aclaracion` en
  la IA, orquestación, `update_last_transaction_to_sheet`, system prompt, mensajes de
  confirmación/aclaración, eval ampliado (casos 31–34 + audio) y **tests: pytest 39/39 ·
  ruff 0 · black sin cambios · mypy sin issues**. Eval en contenedor: monto 96.7%, casos
  31–34 reconocen `corregir`, caso 27 `PIDE_ACLARACION`. **E2E real:** la 2ª nota de voz
  ("corrige, no eran dos, eran 5") actualizó la última fila del teléfono en vez de crear una
  nueva. **2 bugs corregidos:** `tipo_movimiento: null` → `or "Gasto"` (sheets) y
  `AsyncClient` global → por llamada (whatsapp); ambos QA verificados (39/39, ruff, black,
  mypy). → **5.5.4 completado el 12/08 (abajo); falta solo 5.5.5 (suite en CI).**
- **12/08/2026:** **Fase 5.5.4 — ajustes iterativos COMPLETOS.** 7 trampas de regresión A–G en
  `tests/test_precision_regresion.py` + 4 reglas al `SYSTEM_PROMPT_PARSE` (corrección = delta
  (13/08), sin monto no se crea transacción, modismos nunca null, movilidad/Transporte vs.
  Servicios, "Otros" solo último recurso, modismo con número anula aclaración). **Eval real en
  el contenedor: monto/categoría/tipo 100% (peor de 3 corridas)** con el conjunto dorado de 34
  casos / 33 audios. **Tests: pytest 46/46 · ruff 0 · black sin cambios · mypy success
  (15 files).** Pendiente: **5.5.5** (suite de precisión en CI).

### Timeline

| Semana | Hito | Estado |
|---|---|---|
| 1 (Jul 10-14) | Infraestructura: Docker, CI/CD, webhook Meta, HMAC | ✅ |
| 2 (Jul 15-18) | IA: Celery, Whisper, GPT-4o-mini, 22 tests modismos ticos | ✅ |
| 3 (Jul 19-22) | Persistencia: GCP auth, Sheets, orquestación, validación E2E | ✅ |
| 4 (Jul 27-29) | Hardening: rate limiting, health check, caché, tipado webhook, pyproject.toml, CI cleanup, Docker slim, 31 tests | ✅ |
| 5 (Ago 3) | Autenticación Meta: Bearer Token en descarga (3.8.1) + validación descarga 200 OK (3.8.2 a medias) | 🔄 |
| 6 (Ago 5) | App Secret real + firma HMAC validada + suscripción WABA→App + pipeline de IA demostrado sin Meta (Whisper→GPT→Sheets) | ✅ (parcial 3.8.2) |
| 7 (Ago 6) | **E2E real completo con Meta (5.4):** callback URL re-registrado (falso positivo del bloqueo), nota de voz real → Sheets → respuesta WhatsApp | ✅ |
| 8 (Ago 10-12) | **Fase 5.5:** conjunto dorado (5.5.1, **34 casos/33 audios** en v5) + eval automatizado (5.5.2, `specs/eval_precision.py`) — monto ≥96.2% (prompt afinado) · **5.5.3 flujo de corrección 8/8 pasos + E2E real en WhatsApp el 11/08** · **5.5.4 ajustes iterativos + trampas A–G + eval real 100% peor de 3 (12/08, pytest 46/46)** | 🔄 (falta 5.5.5 suite en CI) |

### Pendientes para MVP Comercial

- **Desarrollo Local con ngrok (5.4):** Túnel para pipeline completo en local antes de producción. **✅ COMPLETADO 06/08/2026** — E2E real validado con nota de voz real (falso positivo del bloqueo; ver arriba). Habilita el **PUNTO A** (testeo interno, ≤5 destinatarios en la allowlist).
- **Flujo de corrección por WhatsApp (5.5.3):** "corrige, eran 6 rojos no 5" → el bot actualiza la última transacción y confirma, en vez de crear una nueva (ADR-0010). Incluye pedir aclaración cuando el audio trae dos flujos (caso 27). **✅ COMPLETADO y validado E2E real 11/08/2026** (8/8 pasos, pytest 39/39; la 2ª nota de voz corrigió la última fila del teléfono en WhatsApp).
- **Ajustes iterativos de precisión (5.5.4):** ✅ **COMPLETADO 12/08/2026** — trampas de
  regresión A–G (`tests/test_precision_regresion.py`) + 4 reglas al `SYSTEM_PROMPT_PARSE`
  (`services/openai_service.py:54`); eval real **100% peor de 3**. El caso 9 ("seis tejas" →
  "seis cejas") queda como limitación aceptada de Whisper (trampa E).
- **Suite de precisión en CI (5.5.5):** integrar los tests de regresión al pipeline de CI; el
  eval real (audios + API de OpenAI) se mantiene como paso manual por costo de API.
- **Onboarding Automatizado (6.1):** Mapeo dinámico clientes → spreadsheet por número de teléfono.
- **Autenticación Simplificada (6.3):** Registro inicial por WhatsApp (teléfono = identidad).
- **Despliegue Hetzner + Caddy (5.1):** Producción con HTTPS.

---

## Instalación

```bash
# 1. Clonar
git clone <repo-url> caja-chica-bot
cd caja-chica-bot

# 2. Variables de entorno
cp .env.example .env
# Editar .env con credenciales reales (Meta, OpenAI, GCP)

# 3. Iniciar con Docker
docker compose up --build -d

# 4. Verificar health
curl http://localhost:8000/health

# 5. Correr tests
docker compose exec app python -m pytest tests/ -v
```

### Requisitos
- Docker + Docker Compose
- Cuenta de Meta for Developers (WhatsApp API)
- API Key de OpenAI
- Google Cloud Service Account con permisos en Google Sheets

---

## Uso

1. Envía un mensaje o nota de voz al número de WhatsApp registrado.
2. El bot procesa el audio (Whisper → GPT-4o-mini → Sheets).
3. Recibís una confirmación por WhatsApp con los datos extraídos.
4. Si no entiende el mensaje, recibís un mensaje de cortesía pidiendo reintentar.

### Modismos Soportados
| Término | Significado |
|---|---|
| 1 rojo | ₡1.000 |
| 1 teja | ₡100 |
| 1 teja larga | ₡100.000 |
| 1 tucán | ₡5.000 |

---

## Tiempos de Implementación

| Fase | Estimado | Real | Notas |
|---|---|---|---|
| Docker & CI/CD | 4 h | 5 h | Pipelines gemelos (GitHub + GitLab) |
| Webhook & HMAC | 8 h | 9 h | Validación de firma con pruebas E2E |
| Celery + IA (Whisper + GPT) | 16 h | 15 h | Structured Outputs, 22 tests modismos |
| Google Sheets + Outbound WhatsApp | 10 h | 14 h | Autenticación GCP, orquestación, tests |
| Calidad: lint, types, pyproject.toml | 2 h | 3 h | Black, Ruff, mypy --strict, pytest |
| **Hardening (29/07)** | **6 h** | **8 h** | Rate limiting, health, caché, tipado, CI cleanup, Docker slim, optimización event loop |

---

## ¿Qué Haríamos Distinto?

1. **`pyproject.toml` desde el inicio.** Arrancamos con configs sueltas (`.flake8`, `mypy.ini`, `pytest.ini`, `pyproject.toml` no existía). Centralizar todo en `pyproject.toml` desde el día 1 habría ahorrado 15 minutos de búsqueda y 3 commits de limpieza.
2. **Tipado del webhook en la primera iteración.** Los 7 modelos Pydantic para el payload de Meta se implementaron en la Fase 4 en lugar de la Fase 1. Haberlos definido desde el principio habría prevenido dos bugs de serialización detectados en producción simulada.
3. **slowapi como rate limiter desde el diseño.** La protección contra abuso se postergó a "post-MVP" y luego costó 2 h de integración porque el middleware requiere modificar el `app` object después de creado. Si se hubiera contemplado en la arquitectura inicial, se habría agregado en 15 minutos.
4. **Caché de clientes HTTP desde el inicio.** `gspread` y `httpx.AsyncClient` se instanciaban en cada request. La corrección fue trivial (5 min), pero es el tipo de deuda que escala mal con el número de workers.
5. **Eliminar `test_env_config.py` antes.** Se "reescribió con asserts" en la auditoría del 21/07 pero seguía siendo un archivo que requería `.env` real para correr y no aportaba valor en CI. Se eliminó en la siguiente ronda. Debimos eliminarlo directamente.
6. ~~**Dockerfile multistage.**~~ Ya implementado (builder → runtime) desde el
   03/08/2026; este punto quedó obsoleto.

---

## Seguridad

- **Secretos:** `pydantic-settings` + variables de entorno. Prohibido hardcodear credenciales.
- **GCP:** Archivo JSON de service account fuera del repo en `secrets/`, ignorado por `.gitignore`.
- **HMAC:** Firma `X-Hub-Signature-256` validada en cada webhook entrante.
- **Docker:** `build-essential` y capa `apt-get` eliminados de la imagen final. El
  contenedor corre como root por ahora; el hardening (usuario no-root, filesystem
  read-only, cap_drop) queda pendiente para la Fase 5 (hallazgo #12).
- **CI/CD:** Sin secretos hardcodeados en pipelines. Variables inyectadas desde GitHub/GitLab Secrets.
- **Rate Limiting:** 10 requests/minuto protegen contra abuso de API de OpenAI.

---

## Calidad de Código

| Herramienta | Comando | Resultado |
|---|---|---|
| Black | `black . --check` | Formateo consistente |
| Ruff | `ruff check .` | 0 errores |
| Mypy | `mypy app/ workers/ services/` (config, sin `--strict`, como la CI) | 0 errores en 15 archivos |
| Mypy estricto | `mypy --strict` | **Success: no issues found in 15 source files (05/08/2026)** |
| Pytest | `pytest tests/ -v` | 46/46 passed |

```bash
# QA local (Docker)
MSYS_NO_PATHCONV=1 docker compose exec app python -m pytest tests/ -v
MSYS_NO_PATHCONV=1 docker compose exec app python -m ruff check .
MSYS_NO_PATHCONV=1 docker compose exec app python -m mypy app/ workers/ services/
```
