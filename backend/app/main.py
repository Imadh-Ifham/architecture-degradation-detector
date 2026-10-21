from fastapi import FastAPI

from app.api.degradation import router as degradation_router
from app.api.degradation_scoring import router as degradation_scoring_router
from app.api.health import router as health_router
from app.api.repositories import router as repositories_router
from app.api.validations import router as validations_router
from app.core.config import settings


# Shown on the generated documentation page at /docs. Tags are described here
# because that is the only place FastAPI accepts a description for one, and the
# order below is the order the page lists them in.
TAGS = [
    {"name": "Health", "description": "Liveness of the two shared databases."},
    {
        "name": "Repositories",
        "description": "Ingest a repository and inventory the clone.",
    },
    {
        "name": "Validation",
        "description": (
            "Validate a recovered architecture against the architectural "
            "intent recorded for the same release. Eight stages, of which two "
            "call a language model and the rest are deterministic code."
        ),
    },
    {
        "name": "Degradation",
        "description": (
            "Detect anti-patterns in every validated release of one system, "
            "track them across releases, and report only what is statistically "
            "getting worse."
        ),
    },
    {"name": "Severity scoring", "description": "Saved C4 severity reports (read-only)."},
]

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    openapi_tags=TAGS,
)

app.include_router(health_router)
app.include_router(repositories_router)
app.include_router(validations_router)
app.include_router(degradation_router)
app.include_router(degradation_scoring_router)


@app.get("/")
def root():
    return {
        "message": "Architecture Degradation Detector API",
        "environment": settings.app_env,
    }