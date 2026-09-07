#!/bin/bash
# setup-server.sh — Script de setup para el servidor Hetzner
# Ejecutar como root en el servidor nuevo (Ubuntu 24.04)
# Uso: bash setup-server.sh

set -e

echo "=== Caja Chica Bot — Setup del Servidor ==="
echo ""

# 1. Actualizar sistema
echo "[1/7] Actualizando sistema..."
apt update && apt upgrade -y

# 2. Instalar Docker
echo "[2/7] Instalando Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker $USER
    echo "Docker instalado. Cerrar y volver a abrir sesión para usar Docker sin sudo."
else
    echo "Docker ya instalado."
fi

# 3. Instalar Docker Compose
echo "[3/7] Verificando Docker Compose..."
if ! docker compose version &> /dev/null; then
    apt install docker-compose-plugin -y
fi
echo "Docker Compose OK."

# 4. Crear directorio de la app
echo "[4/7] Creando directorio de la app..."
mkdir -p /opt/caja-chica-bot
cd /opt/caja-chica-bot

# 5. Clonar repositorio
echo "[5/7] Clonando repositorio..."
if [ -d ".git" ]; then
    echo "Repositorio ya existe. Actualizando..."
    git pull origin main
else
    git clone https://github.com/ericksuper8000-source/caja-chica-bot.git .
    git checkout main
fi

# 6. Configurar .env.production
echo "[6/7] Configurando variables de entorno..."
if [ ! -f ".env.production" ]; then
    cp .env.production .env.production.example
    echo ""
    echo "=========================================="
    echo "IMPORTANTE: Editar .env.production con tus valores reales:"
    echo "  nano /opt/caja-chica-bot/.env.production"
    echo ""
    echo "Variables requeridas:"
    echo "  - WHATSAPP_API_TOKEN"
    echo "  - WHATSAPP_PHONE_NUMBER_ID"
    echo "  - WHATSAPP_VERIFY_TOKEN"
    echo "  - WHATSAPP_APP_SECRET"
    echo "  - GOOGLE_SHEETS_SPREADSHEET_ID"
    echo "=========================================="
    echo ""
else
    echo ".env.production ya existe."
fi

# 7. Configurar DNS (instrucciones)
echo "[7/7] Verificando DNS..."
echo ""
echo "=========================================="
echo "CONFIGURAR DNS EN CLOUDFLARE:"
echo ""
echo "Tipo  | Nombre  | Contenido"
echo "------|---------|------------------"
echo "A     | @       | <IP_DEL_SERVIDOR>"
echo "A     | www     | <IP_DEL_SERVIDOR>"
echo ""
echo "IP del servidor: $(curl -s ifconfig.me)"
echo "=========================================="
echo ""

# Verificar que los archivos de configuración existen
echo "=== Verificando archivos de configuración ==="
for file in docker-compose.prod.yml Caddyfile Dockerfile.prod .dockerignore; do
    if [ -f "$file" ]; then
        echo "  ✓ $file"
    else
        echo "  ✗ $file FALTA"
    fi
done

echo ""
echo "=== Setup completado ==="
echo ""
echo "Siguientes pasos:"
echo "1. Editar .env.production con tus valores reales"
echo "2. Copiar la llave GCP a secrets/:"
echo "   mkdir -p secrets"
echo "   cp /ruta/a/tu/gcp_key.json secrets/gcp_key.json"
echo "3. Configurar DNS en Cloudflare (ver arriba)"
echo "4. Desplegar:"
echo "   docker compose -f docker-compose.prod.yml up -d --build"
echo "5. Verificar:"
echo "   curl https://cajachicacr.com/health"
echo ""
