from fastapi import FastAPI
from api.routers import transcribe, challenge
from api.routers import memory, collaborators
from db.database import init_db

app = FastAPI(title="RECALL API", version="2.0.0")


@app.on_event("startup")
def startup():
    """Run Alembic migrations on every startup (idempotent)."""
    init_db()


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "2.0.0"}


app.include_router(transcribe.router, prefix="/api/v1")
app.include_router(challenge.router, prefix="/api/v1")
app.include_router(memory.router, prefix="/api/v1")
app.include_router(collaborators.router, prefix="/api/v1")
