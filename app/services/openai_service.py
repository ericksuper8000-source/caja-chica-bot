import os
import logging
from typing import Optional, Dict, Any, Literal
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from app.config import settings

logger = logging.getLogger(__name__)

# Configuración del cliente
_api_key: str = settings.OPENAI_API_KEY or "sk-mock-key-for-testing-purposes-only"
openai_client: AsyncOpenAI = AsyncOpenAI(api_key=_api_key)


class TransactionResponse(BaseModel):
    monto: int = Field(description="Monto numérico exacto de la transacción.")
    categoria: str = Field(description="Categoría del movimiento.")
    tipo_movimiento: Literal["Gasto", "Ingreso"] = Field(
        description="El tipo de flujo."
    )
    detalle: str = Field(description="Descripción concisa.")


async def transcribir_audio_whisper(file_path: str) -> Optional[str]:
    if not os.path.exists(file_path):
        logger.error(f"El archivo {file_path} no existe.")
        return None

    try:
        with open(file_path, "rb") as audio_file:
            transcript = await openai_client.audio.transcriptions.create(
                model="whisper-1", file=audio_file, language="es"
            )
            return str(transcript.text)
    except Exception as e:
        logger.error(f"Error en Whisper: {str(e)}")
        return None


async def parse_financial_text(text_input: str) -> Optional[Dict[str, Any]]:
    if not text_input or not text_input.strip():
        return None

    system_prompt: str = (
        "Actúas como un extractor financiero experto en Costa Rica..."  # (Tu prompt original)
    )

    try:
        response = await openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text_input},
            ],
            response_format=TransactionResponse,
        )

        parsed_message = response.choices[0].message.parsed
        if parsed_message:
            # Aquí Mypy estaba fallando, ahora indicamos explícitamente el retorno
            return parsed_message.model_dump()
        return None

    except Exception as e:
        logger.error(f"Error en OpenAI: {str(e)}")
        return None
