from fastapi import FastAPI

app = FastAPI(title="Caja Chica Bot API", version="0.1.0")


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Endpoint de sanidad."""
    return {"status": "healthy"}
