# Guía de Deployment — Fase 5.1

## Requisitos previos
- [ ] Cuenta Hetzner con método de pago
- [ ] Dominio `cajachicacr.com` configurado en Cloudflare
- [ ] Código en GitHub actualizado (último commit en `main`)

---

## Paso 1: Crear servidor en Hetzner

1. Ir a https://console.hetzner.com/cloud
2. **New Project** → nombre: `caja-chica-bot`
3. **Add Server**
   - Location: US (o la más cercana)
   - Image: Ubuntu 24.04
   - Type: CX22 (2 vCPU, 4 GB RAM, ~€4.59/mes)
   - SSH key: agregar tu clave pública
   - Name: `caja-chica-prod`
4. **Create & Buy** → esperar ~2 minutos
5. **Copiar la IP** del servidor

---

## Paso 2: Configurar DNS en Cloudflare

1. Ir a https://dash.cloudflare.com → `cajachicacr.com`
2. **DNS** → **Add record**
   - Type: `A`
   - Name: `@`
   - Content: `<IP_DEL_SERVIDOR>`
   - Proxy: DNS only (el SSL lo maneja Caddy)
   - TTL: Auto
3. **Add another**
   - Type: `A`
   - Name: `www`
   - Content: `<IP_DEL_SERVIDOR>`
   - Proxy: DNS only
4. Verificar: `ping cajachicacr.com` debe resolver a la IP del servidor

---

## Paso 3: Conectarse al servidor

```bash
ssh root@<IP_DEL_SERVIDOR>
```

---

## Paso 4: Ejecutar setup

```bash
# Descargar el script
curl -O https://raw.githubusercontent.com/ericksuper8000-source/caja-chica-bot/main/scripts/setup-server.sh

# Ejecutar
bash setup-server.sh
```

O ejecutar manualmente los pasos del script.

---

## Paso 5: Configurar variables de entorno

```bash
cd /opt/caja-chica-bot
nano .env.production
```

Completar con los valores reales (los mismos del `.env` local):
- `WHATSAPP_API_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_APP_SECRET`
- `GOOGLE_SHEETS_SPREADSHEET_ID`

---

## Paso 6: Copiar credenciales GCP

```bash
mkdir -p secrets
# Copiar desde tu máquina local
scp /ruta/a/caja-chica-bot-prod-*.json root@<IP>:/opt/caja-chica-bot/secrets/gcp_key.json
```

---

## Paso 7: Desplegar

```bash
cd /opt/caja-chica-bot

# Build y levantar
docker compose -f docker-compose.prod.yml up -d --build

# Verificar estado
docker compose -f docker-compose.prod.yml ps

# Verificar logs
docker compose -f docker-compose.prod.yml logs -f app
```

---

## Paso 8: Verificar

```bash
# Health check
curl https://cajachicacr.com/health

# Webhook handshake
curl "https://cajachicacr.com/v1/whatsapp/webhook?hub.mode=subscribe&hub.challenge=test123&hub.verify_token=<TU_VERIFY_TOKEN>"
```

Respuesta esperada: `test123`

---

## Paso 9: Actualizar webhook en Meta

1. Ir a https://developers.facebook.com → app `CajaChica`
2. WhatsApp → Configuration → Webhook
3. **Callback URL**: `https://cajachicacr.com/v1/whatsapp/webhook`
4. **Verify Token**: el mismo del `.env`
5. **Subscribe** to messages
6. Verificar que el webhook responda 200

---

## Paso 10: Probar E2E

1. Enviar nota de voz al número de prueba desde tu WhatsApp
2. Verificar en los logs:
   ```bash
   docker compose -f docker-compose.prod.yml logs -f worker
   ```
3. Verificar que la transacción aparezca en Google Sheets
4. Verificar que recibas la respuesta en WhatsApp

---

## Troubleshooting

### El webhook no responde
```bash
# Verificar logs de Caddy
docker compose -f docker-compose.prod.yml logs caddy

# Verificar que la app esté corriendo
docker compose -f docker-compose.prod.yml ps
```

### SSL no funciona
- Verificar que el DNS esté propagado: `dig cajachicacr.com`
- Caddy auto-genera el certificado en ~60 segundos después de la primera petición

### Los mensajes no llegan
- Verificar que el webhook esté registrado en Meta con la URL correcta
- Verificar en ngrok dashboard si hay POSTs entrantes (temporal, para debugging)

---

## Comandos útiles

```bash
# Ver logs en tiempo real
docker compose -f docker-compose.prod.yml logs -f

# Reiniciar solo la app
docker compose -f docker-compose.prod.yml restart app

# Ver logs del worker
docker compose -f docker-compose.prod.yml logs -f worker

# Entrar al contenedor de la app
docker compose -f docker-compose.prod.yml exec app bash

# Parar todo
docker compose -f docker-compose.prod.yml down

# Actualizar y redeploy
git pull
docker compose -f docker-compose.prod.yml up -d --build
```
