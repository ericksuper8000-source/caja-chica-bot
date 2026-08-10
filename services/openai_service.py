import logging
import os
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

# En CI/CD no hay .env, usamos un placeholder para que el módulo pueda importarse.
# Los tests mockean las llamadas a la API, así que la key real nunca se usa en pruebas.
_api_key = settings.OPENAI_API_KEY or "sk-placeholder-ci-only"
openai_client = AsyncOpenAI(api_key=_api_key)


# ==========================================
# 1. ESQUEMAS DE ENTORNO Y MODELOS ESTRUCTURADOS
# ==========================================
class TransactionResponse(BaseModel):
    monto: int = Field(description="Monto numérico exacto de la transacción financiera.")
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
async def transcribir_audio_whisper(file_path: str) -> str | None:
    """
    Recibe la ruta local de un archivo de audio (.ogg / .mp3), lo procesa
    a través de OpenAI Whisper API y retorna la transcripción adaptada al acento tico.
    """
    if not os.path.exists(file_path):
        logger.error("El archivo de audio no existe en la ruta %s", file_path)
        return None

    try:
        with open(file_path, "rb") as audio_file:
            transcript = await openai_client.audio.transcriptions.create(
                model="whisper-1", file=audio_file, language="es"
            )
            return transcript.text
    except Exception as e:
        logger.error("Error en la capa de transcripción Whisper: %s", e)
        return None


# ==========================================
# 3. SERVICIO DE EXTRACCIÓN ESTRUCTURADA - PASO 2.5
# ==========================================
async def parse_financial_text(text_input: str) -> dict[str, Any] | None:
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
        "Reglas estrictas sobre montos:\n"
        "- TODOS los montos van en COLONES (Costa Rica). Nunca conviertas a dólares.\n"
        "- Ignora símbolos de moneda y separadores de miles: '$3,000' o '$ 3.000' = 3000 "
        "colones; '8,000' = 8000. El monto final SIEMPRE es un entero sin símbolos.\n"
        "- Si el monto aparece en forma de dos flujos separados (un ingreso Y un gasto en el "
        "mismo mensaje), NO registres ninguno: retorna nulo (el sistema pedirá aclaración al "
        "usuario, pues solo se registra un movimiento a la vez).\n"
        "Reglas estrictas de categoría:\n"
        "- Usa SIEMPRE exactamente una de estas categorías: Alimentación, Transporte, "
        "Servicios, Compras, Ventas, Personal, Trabajo, Otros.\n"
        "- 'categoria' describe el TIPO de gasto/ingreso del negocio; 'detalle' describe qué "
        "se compró/recibió exactamente.\n"
        "- Comprar inventario, mercadería, productos, stock o equipo para el negocio = "
        "categoría 'Compras'.\n"
        "- Un pago/ingreso de trabajo o jornal = 'Trabajo'. Un pago a un empleado/ayudante = "
        "'Personal'.\n"
        "- Dinero entrante por ventas, pedidos o clientes = 'Ventas'.\n"
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
        logger.error("Error procesando Structured Outputs con OpenAI: %s", e)
        return None
