import os
import httpx
from workers.celery_app import celery_app
from app.config import settings


@celery_app.task(name="workers.tasks.download_audio_task")
def download_audio_task(media_id: str) -> str:
    """Tarea asíncrona de Celery que consulta la API de Meta para obtener

    la URL de un archivo de audio, lo descarga y lo almacena temporalmente.
    """
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"}

    # Usamos httpx.Client() para ejecutar llamadas sincrónicas dentro del worker tradicional de Celery
    with httpx.Client() as client:
        # Paso A: Obtener la URL del recurso multimedia usando el media_id
        meta_url = f"https://graph.facebook.com/v18.0/{media_id}"
        response = client.get(meta_url, headers=headers)
        response.raise_for_status()
        media_data = response.json()

        download_url = media_data.get("url")
        if not download_url:
            raise ValueError(
                f"No se encontró la URL de descarga para el media_id: {media_id}"
            )

        # Paso B: Descargar los bytes reales del archivo .ogg
        audio_response = client.get(download_url, headers=headers)
        audio_response.raise_for_status()
        audio_content = audio_response.content

    # Guardar temporalmente el archivo en el disco local
    os.makedirs("/tmp/caja_chica", exist_ok=True)
    file_path = f"/tmp/caja_chica/{media_id}.ogg"

    with open(file_path, "wb") as f:
        f.write(audio_content)

    return file_path
