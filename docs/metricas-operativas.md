# Métricas operativas — Caja Chica Bot

> **Objetivo:** saber si el servicio está sano y si el dato está protegido, sin montar
> Prometheus ni exponer datos de clientes. Las métricas de negocio se consultan en la
> hoja y en los logs.

---

## 1. Disponibilidad

| Qué | Dónde | Qué mirar |
|---|---|---|
| App + Redis + Celery | `GET /health` | `status: healthy`; si es 503, el detalle indica el componente |
| Uptime del proceso | `GET /metrics` | `uptime_segundos` |
| Contenedores | `docker compose ps` | `app` healthy; `worker`/`beat`/`caddy`/`redis` Up |
| Alertas | WhatsApp a `ADMIN_PHONE` | una alerta por caída y un aviso de recuperación |

```bash
curl -sS https://cajachicacr.com/health
curl -sS https://cajachicacr.com/metrics
docker compose -f docker-compose.prod.yml ps
```

---

## 2. Backups

`/metrics` devuelve:

```json
{
  "uptime_segundos": 12345,
  "entorno": "production",
  "backups": {
    "total": 7,
    "ultimo": "caja-chica-backup-20261108-230000.zip",
    "ultimo_tamano_bytes": 123456
  }
}
```

- **`total > 0`** y un `ultimo` reciente → el backup diario está corriendo.
- Verificar el contenido con `scripts/verificar_backup.py` (ver runbook).
- Si `total` no crece en 24 h, revisar `crear_backup_task` y el disco.

---

## 3. Errores y actividad (desde logs)

```bash
# Conteo de errores de las últimas 24 h (sin imprimir PII)
docker compose -f docker-compose.prod.yml logs --since 24h app worker 2>&1 \
  | grep -c -E "ERROR|Traceback|CRITICAL"

# Actividad de backups
docker compose -f docker-compose.prod.yml logs --since 24h worker 2>&1 \
  | grep "crear_backup_task"
```

- **Meta:** 0 errores no controlados por día.
- **Movimientos/día:** se leen de la hoja o de los logs de confirmación; no se exponen
  en `/metrics` para no filtrar datos de clientes.
- **Latencia percibida:** comparar el timestamp del mensaje con el de la respuesta; el
  objetivo histórico es ~13 s en audio.

---

## 4. Alertas que ya existen

| Alerta | Origen | Cuándo |
|---|---|---|
| Salud caída | `verificar_salud_task` | `/health` no responde o devuelve 503 |
| Recuperación | `verificar_salud_task` | vuelve a responder tras una caída |
| Backup fallido | logs de `crear_backup_task` | el backup devuelve `ERROR` |
| Presupuesto 80/100% | pipeline de presupuestos | gasto cruza el umbral (cliente) |

---

## 5. Rutina semanal sugerida (5 minutos)

1. `GET /health` y `GET /metrics`.
2. `docker compose ps`.
3. Confirmar que hay un backup de las últimas 24 h.
4. Contar errores en logs de los últimos 7 días.
5. Revisar que `ADMIN_PHONE` sigue configurado (si cambió el número del dueño).
