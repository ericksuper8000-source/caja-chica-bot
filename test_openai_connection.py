from openai import OpenAI
from app.config import settings


def test_connection():
    try:
        # Inicializa el cliente usando la llave cargada en settings
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        # Realiza una petición mínima para listar modelos
        models = client.models.list()

        print("¡Conexión exitosa con OpenAI!")
        print(f"Primer modelo disponible: {models.data[0].id}")

    except Exception as e:
        print(f"Error en la conexión: {e}")


if __name__ == "__main__":
    test_connection()
