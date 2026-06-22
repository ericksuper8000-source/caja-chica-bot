import hmac
import hashlib
from fastapi import Header, HTTPException, Request

# En el siguiente paso leeremos esto dinámicamente, por ahora lo dejamos fijo para la prueba
APP_SECRET = "mi_clave_secreta_de_meta_super_segura"

async def validar_firma_whatsapp(request: Request, x_hub_signature_256: str = Header(None)) -> None:
    """
    Paso 1.3: Verifica que el paquete venga de Meta calculando el hash HMAC-SHA256
    del cuerpo de la petición y comparándolo con el encabezado X-Hub-Signature-256.
    """
    # 1. Si no viene el sello en la caja, cerramos la puerta de inmediato
    if not x_hub_signature_256:
        raise HTTPException(status_code=403, detail="Falta la firma de seguridad")
    
    # 2. El encabezado viene con el formato 'sha256=xxxx', le quitamos el prefijo
    try:
        signature_prefix, actual_signature = x_hub_signature_256.split("=")
        if signature_prefix != "sha256":
            raise HTTPException(status_code=403, detail="Formato de firma inválido")
    except ValueError:
        raise HTTPException(status_code=403, detail="Estructura de firma dañada")

    # 3. Leemos el contenido real del paquete (los bytes puros que envió el cartero)
    body_bytes = await request.body()

    # 4. Hacemos la matemática: Calculamos nuestro propio sello usando nuestro secreto
    expected_signature = hmac.new(
        key=APP_SECRET.encode("utf-8"),
        msg=body_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()

    # 5. Comparamos de forma segura que ambos sellos sean idénticos
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise HTTPException(status_code=403, detail="Firma inválida. Origen no legítimo.")