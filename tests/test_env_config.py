from app.config import settings


def test_config_loading():
    print("--- Verificando carga de variables de entorno ---")
    # Verificamos si los campos tienen contenido (solo longitud, no el valor)
    token_len = len(settings.WHATSAPP_API_TOKEN)
    phone_id_len = len(settings.WHATSAPP_PHONE_NUMBER_ID)
    
    print(f"WHATSAPP_API_TOKEN cargado: {'Sí' if token_len > 0 else 'No'} (Longitud: {token_len})")
    print(f"WHATSAPP_PHONE_NUMBER_ID cargado: {'Sí' if phone_id_len > 0 else 'No'} (Longitud: {phone_id_len})")
    
    if token_len > 0 and phone_id_len > 0:
        print("¡ÉXITO! Las variables de WhatsApp fueron cargadas correctamente.")
    else:
        print("ERROR: Alguna variable no se cargó. Revisa tu archivo .env.")

if __name__ == "__main__":
    test_config_loading()