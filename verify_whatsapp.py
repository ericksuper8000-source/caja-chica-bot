import httpx
from app.config import settings

def test_whatsapp_connection():
    token = settings.WHATSAPP_API_TOKEN
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    
    if not token or not phone_id:
        print("ERROR: Token o Phone ID no configurados en el .env")
        return

    url = f"https://graph.facebook.com/v18.0/{phone_id}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with httpx.Client() as client:
            response = client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"CONEXIÓN EXITOSA: Nombre del número: {data.get('verified_name')}")
            else:
                print(f"ERROR: Respuesta de Meta {response.status_code}")
                print(response.json())
    except Exception as e:
        print(f"ERROR DE CONEXIÓN: {e}")

if __name__ == "__main__":
    test_whatsapp_connection()