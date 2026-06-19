from fastapi import FastAPI

app = FastAPI(
    title="Caja Chica Bot API",
    description="Backend modular para la automatización y gestión de flujos",
    version="0.1.0"
)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "environment": "local",
        "database": "pending",
        "redis": "pending"
    }