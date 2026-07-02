import httpx
from app.config import settings


class LLMService:
    def __init__(self) -> None:
        # Usamos las configuraciones validadas en config.py
        self.api_key = settings.OPENAI_API_KEY
        # Si usas Ollama local, la URL base cambiaría aquí
        self.base_url = "https://api.openai.com/v1"

    async def generate_response(self, prompt: str) -> str:
        """
        Envía un prompt al modelo configurado.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"])


# Instancia global para usar en toda la app
llm_service = LLMService()
