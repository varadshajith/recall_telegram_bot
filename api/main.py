from fastapi import FastAPI
from api.routers import transcribe, challenge
from db.database import init_db

app = FastAPI(title="RECALL API", version="0.1.0")

# Initialize database on startup - this creates the SQLite file and tables
@app.on_event("startup")
def startup():
    init_db()

# Health check - a simple "Are you alive?" endpoint
@app.get("/health")
def health_check():
    return {"status": "ok"}

# Include our specialized "Front Desks"
app.include_router(transcribe.router, prefix="/api/v1")
app.include_router(challenge.router, prefix="/api/v1")
