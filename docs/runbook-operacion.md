# Runbook de operación — Caja Chica Bot

> **Alcance:** qué hacer cuando algo falla en producción. No reemplaza el juicio del
> dueño ni la revisión de logs; da el orden correcto para no perder datos ni dinero.
> **Regla de oro:** primero se protege el dato (backup/rollback), después se investiga.

---

## 1. Chequeos rápidos

```bash
cd /opt/caja-chica-bot

# ¿Están los contenedores?
docker compose -f docker-compose.prod.yml ps

# ¿La app responde?
curl -sS https://cajachicacr.com/health

# Métricas mínimas (uptime + backups)
curl -sS https://cajachicacr.com/metrics
```

**Salud esperada:** `{"redis":"ok","celery":"ok","status":"healthy"}`.
Si `/health` devuelve 503, el detalle dice qué componente falla.

---

## 2. Monitoreo automático

- Celery beat ejecuta `workers.tasks.verificar_salud_task` **cada 5 minutos**.
- Consulta `HEALTHCHECK_URL` (por defecto `http://app:8000/health`).
- Si la app deja de responder, envía **una** alerta por WhatsApp a `ADMIN_PHONE`.
- Cuando vuelve, envía un mensaje de recuperación.
- El estado se guarda en Redis (`monitor:salud:estado`, TTL 24 h) para no repetir alertas.
- **Si `ADMIN_PHONE` está vacío, no hay alerta.** Configurarlo en `.env.production` y
  recrear `worker`/`beat`:
  ```bash
  docker compose -f docker-compose.prod.yml up -d worker beat
  ```

### 2.1 Límite de mensajes por teléfono (Seguridad #10)

- El pipeline permite **20 mensajes por minuto por teléfono** (`RATE_LIMIT_MENSAJES_POR_MINUTO`).
- Si se supera, responde “Estás mandando muchos mensajes seguidos…” y no llama a OpenAI
  ni a Sheets.
- Si Redis falla, el mensaje **se permite** (degradación segura).
- El límite por IP del webhook sigue activo como primera barrera.

---

## 3. Verificar un backup (no escribe nada)

```bash
docker compose -f docker-compose.prod.yml exec -T app \
  python scripts/verificar_backup.py /backups/caja-chica-backup-AAAAMMDD-HHMMSS.zip
```

- Código 0 y `"valido": true` → el backup se puede leer y los conteos coinciden con el
  `MANIFEST.txt`.
- Código 1 → **no usar ese backup**. Revisar si hay otro más reciente y por qué falló el
  backup (disco lleno, API de Sheets, etc.).

---

## 4. Restaurar un backup (solo en una copia)

**Nunca restaurar sobre la hoja de producción.** El script reemplaza el contenido de las
pestañas.

1. Descargar el `.zip` desde el VPS o copiarlo a una máquina segura.
2. Crear una **copia** del spreadsheet (Google Sheets → Archivo → Crear una copia).
3. Dry-run (solo cuenta):
   ```bash
   docker compose -f docker-compose.prod.yml exec -T app \
     python scripts/restaurar_backup.py /backups/backup.zip \
     --spreadsheet-id <ID_DE_LA_COPIA>
   ```
4. Restauración real en la copia:
   ```bash
   docker compose -f docker-compose.prod.yml exec -T app \
     python scripts/restaurar_backup.py /backups/backup.zip \
     --spreadsheet-id <ID_DE_LA_COPIA> --confirmar
   ```
5. Comparar filas/totales de la copia contra el `MANIFEST.txt` y la hoja original.
6. Si todo cuadra, recién entonces decidir con el dueño cómo reemplazar producción.

---

## 5. Incidentes comunes

| Síntoma | Qué revisar | Acción |
|---|---|---|
| `/health` 503 y `redis=error` | `docker compose ps redis`, logs de redis | Reiniciar `redis`; si persiste, revisar disco/memoria |
| `/health` 503 y `celery=no_workers` | `docker compose ps worker`, logs del worker | Reiniciar `worker`; revisar tareas trabadas |
| La app no responde | `docker compose ps app`, logs de app | Reiniciar `app`; si el contenedor reinicia solo, revisar `docker events` |
| WhatsApp responde 401/403 | Token vencido/rotado, `WHATSAPP_API_TOKEN` | Rotar token en Meta y actualizar `.env.production`; recrear `app`/`worker` |
| Sheets devuelve 403/429 | Permisos de la service account, cuota | Revisar compartir de la hoja; esperar cuota; no reintentar en bucle |
| Disco lleno | `df -h /`, tamaño de `/backups` | Purgar backups viejos; ampliar disco; no borrar la hoja |
| Backup falló | Logs de `crear_backup_task` | Corregir causa y ejecutar la tarea de nuevo |
| Movimiento no aparece | Logs del worker, hoja del cliente | Verificar que el guardado devolvió éxito; no confirmar al usuario sin fila |

---

## 6. Rollback de código

Antes de cada deploy, guardar el commit/imagen actual. Si el deploy rompe algo:

```bash
cd /opt/caja-chica-bot
git status --short          # ver cambios locales
git log -1 --oneline        # commit actual
# Restaurar los archivos desde el respaldo del deploy o volver al commit anterior:
git checkout -- <archivos>
docker compose -f docker-compose.prod.yml up -d --build
```

Si el deploy fue por copia directa (sin commit), usar el tar de respaldo creado antes
del deploy (por ejemplo `/root/caja-chica-runtime-backup-*.tar.gz`) y reconstruir.

---

## 7. Rotación de `WHATSAPP_VERIFY_TOKEN` (Seguridad #10)

El token de verificación del webhook estuvo expuesto en el pasado; hay que rotarlo antes
de cobrar. **No pegarlo en el chat ni en documentos.**

1. Generar uno nuevo (32 bytes hex):
   ```bash
   openssl rand -hex 32
   ```
2. En Meta → app `CajaChica` → WhatsApp → Configuration → Webhook, cambiar el
   **Verify Token** por el nuevo.
3. En el VPS, actualizar `WHATSAPP_VERIFY_TOKEN` en `.env.production` (sin imprimirlo).
4. Recrear la app para que tome el valor:
   ```bash
   docker compose -f docker-compose.prod.yml up -d app
   ```
5. Verificar el handshake con el token nuevo (reemplazar `<TOKEN>` sin mostrarlo):
   ```bash
   curl "https://cajachicacr.com/v1/whatsapp/webhook?hub.mode=subscribe&hub.challenge=test123&hub.verify_token=<TOKEN>"
   # Debe devolver: test123
   ```
6. Confirmar que el bot sigue recibiendo mensajes y recién entonces descartar el token
   viejo.

---

## 8. Contacto y escalamiento

- Dueño: WhatsApp administrativo configurado en `ADMIN_PHONE`.
- No compartir tokens, `.env.production` ni la llave GCP por chat.
- Si hay pérdida de datos, **detener escrituras**, verificar el último backup y restaurar
  primero en una copia.
