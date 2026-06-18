from fastapi import FastAPI

app = FastAPI(
    title="Connect Do API",
    description="Backend oficial de la aplicación móvil Connect Do.",
    version="0.1.0",
)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "connect-do-api",
        "version": "0.1.0",
    }