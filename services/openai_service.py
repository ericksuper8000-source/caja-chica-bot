import os
from typing import Any, Optional, Literal
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from app.config import settings

# Si la llave viene vacía (como en GitHub Actions), usamos un valor ficticio
_api_key = settings.OPENAI_API_KEY or "sk-mock-key-for-testing-purposes-only"
openai_client = AsyncOpenAI(api_key=_api_key)


# ==========================================
# 1. ESQUEMAS DE ENTORNO Y MODELOS ESTRUCTURADOS
# ==========================================
class TransactionResponse(BaseModel):
    monto: int = Field(
        description="Monto numérico exacto de la transacción financiera."
    )
    categoria: str = Field(
        description="Categoría del movimiento (ej: Alimentación, Transporte, Servicios)."
    )
    tipo_movimiento: Literal["Gasto", "Ingreso"] = Field(
        description="El tipo de flujo financiero estrictamente."
    )
    detalle: str = Field(description="Descripción concisa o motivo de la transacción.")


# ==========================================
# 2. SERVICIO DE TRANSCRIPCIÓN (WHISPER)
# ==========================================
async def transcribir_audio_whisper(file_path: str) -> Optional[str]:
    """
    Procesa audio a través de OpenAI Whisper API y retorna la transcripción.
    """
    if not os.path.exists(file_path):
        print(f"Error: El archivo de audio no existe en la ruta {file_path}")
        return None

    try:
        with open(file_path, "rb") as audio_file:
            transcript = await openai_client.audio.transcriptions.create(
                model="whisper-1", file=audio_file, language="es"
            )
            return transcript.text
    except Exception as e:
        print(f"Error en la capa de transcripción Whisper: {str(e)}")
        return None


# ==========================================
# 3. SERVICIO DE EXTRACCIÓN ESTRUCTURADA
# ==========================================
async def parse_financial_text(text_input: str) -> Optional[dict[str, Any]]:
    """
    Procesa texto con GPT-4o-mini y Structured Outputs.
    """
    if not text_input or not text_input.strip():
        return None

    system_prompt = (
        "Actúas como un extractor financiero experto en Costa Rica. Tu tarea es extraer la "
        "información financiera de los mensajes de los usuarios y estructurarla según el esquema provisto.\n\n"
        "Reglas estrictas de conversión para modismos costarricenses:\n"
        "- 'rojos' o 'un tucán' equivalen a múltiplos de 5000.\n"
        "- 'tejas' equivalen a múltiplos de 100.\n"
        "Si el mensaje no contiene datos financieros válidos, retorna nulo."
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
            return parsed_message.model_dump()
        return None

    except Exception as e:
        print(f"Error procesando Structured Outputs con OpenAI: {str(e)}")
        return None


# ==========================================
# 4. FUNCIÓN PUENTE (ORQUESTADOR DE IA)
# ==========================================
async def procesar_audio_a_transaccion(file_path: str) -> Optional[dict[str, Any]]:
    """
    Orquestador de IA: Transcribe el audio y extrae los datos financieros.
    """
    text = await transcribir_audio_whisper(file_path)
    if not text:
        return None
    return await parse_financial_text(text)