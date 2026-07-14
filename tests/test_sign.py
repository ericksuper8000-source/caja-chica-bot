import hashlib
import hmac
from app.config import settings

# Cuerpo del mensaje de prueba
payload = b'{"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"messages": [{"type": "audio", "audio": {"id": "TEST_MEDIA_123"}, "from": "123456789"}]}}]}]}'

# Cálculo de la firma usando el secret real de tus configuraciones
signature = hmac.new(
    settings.WHATSAPP_APP_SECRET.encode("utf-8"), payload, hashlib.sha256
).hexdigest()

print(f"Firma calculada: sha256={signature}")
