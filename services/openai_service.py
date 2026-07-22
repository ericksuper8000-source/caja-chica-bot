import os
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from typing import Optional, Literal
from app.config import settings

# En CI/CD no hay .env, usamos un placeholder para que el módulo pueda importarse.
# Los tests mockean las llamadas a la API, así que la key real nunca se usa en pruebas.
_api_key = settings.OPENAI_API_KEY or "sk-placeholder-ci-only"
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
# 2. SERVICIO DE TRANSCRIPCIÓN (WHISPER) - PASO 2.4
# ==========================================
async def transcribir_audio_whisper(file_path: str) -> Optional[str]:
    """
    Recibe la ruta local de un archivo de audio (.ogg / .mp3), lo procesa
    a través de OpenAI Whisper API y retorna la transcripción adaptada al acento tico.
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
# 3. SERVICIO DE EXTRACCIÓN ESTRUCTURADA - PASO 2.5
# ==========================================
async def parse_financial_text(text_input: str) -> Optional[dict]:
    """
    Procesa una entrada de texto utilizando GPT-4o-mini y Structured Outputs.
    Traduce los modismos costarricenses (ej: rojos, tejas, tucanes) a valores enteros.
    """
    if not text_input or not text_input.strip():
        return None

    system_prompt = (
        "Actúas como un extractor financiero experto en Costa Rica. Tu tarea es extraer la "
        "información financiera de los mensajes de los usuarios y estructurarla según el esquema "
        "provisto.\n\n"
        "Reglas estrictas de conversión para modismos costarricenses:\n"
        "- 'rojo' = ₡1,000 colones (Ej: 5 rojos = 5000, 10 rojos = 10000).\n"
        "- 'tucán' = ₡5,000 colones.\n"
        "- 'teja' = ₡100 colones (Ej: 5 tejas = 500).\n"
        "- 'teja larga' = ₡100,000 colones.\n"
        "Si el mensaje no contiene datos financieros válidos, debes retornar nulo."
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
            if isinstance(parsed_message, dict):
                return parsed_message
            return parsed_message.model_dump()
        return None

    except Exception as e:
        print(f"Error procesando Structured Outputs con OpenAI: {str(e)}")
        return None
