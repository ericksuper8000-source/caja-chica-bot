import os
from openai import AsyncOpenAI
from app.config import settings

# Inicialización del cliente asíncrono utilizando la configuración estricta
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def transcribir_audio_whisper(file_path: str) -> str:
    """Envía un archivo de audio local (.ogg) a la API de OpenAI Whisper

    para su transcripción asíncrona, optimizado para el contexto tico.

    Args:
        file_path (str): Ruta absoluta o relativa del archivo de audio en el disco.

    Returns:
        str: El texto extraído de la nota de voz.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"No se encontró el archivo de audio en la ruta: {file_path}"
        )

    # Abrimos el archivo de forma binaria segura para la API
    with open(file_path, "rb") as audio_file:
        transcription = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="es",  # Forzamos español para mejorar precisión
            prompt="Transcribe esta nota de voz sobre control de dinero, gastos, ingresos y finanzas de una pyme en Costa Rica. Ignora muletillas.",
        )

    return str(transcription.text)
