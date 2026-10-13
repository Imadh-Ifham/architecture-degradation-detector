from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.repositories import router as repositories_router
from app.core.config import settings


app = FastAPI(title=settings.app_name)

app.include_router(health_router)
app.include_router(repositories_router)


@app.get("/")
def root():
    return {
        "message": "Architecture Degradation Detector API",
        "environment": settings.app_env,
    }