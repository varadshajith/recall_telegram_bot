# RECALL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram bot that transcribes voice messages with local Whisper, extracts structured dev briefs via Claude API, and stores results in SQLite.

**Architecture:** FastAPI server queues jobs to Celery; Celery workers run Whisper locally and call Claude API; Telegram bot polls for messages and displays results.

**Tech Stack:** Python 3.11, FastAPI, Celery + Redis, SQLAlchemy, openai-whisper, anthropic SDK, python-telegram-bot

---

## File Structure

```
recall/
├── api/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, health check
│   ├── deps.py              # DB session, auth dependencies
│   └── routers/
│       ├── __init__.py
│       ├── transcribe.py    # POST /transcribe, GET /jobs/{id}
│       └── challenge.py     # POST /challenge
├── bot/
│   ├── __init__.py
│   ├── main.py              # Telegram bot entry point
│   └── handlers.py          # Voice message handler, commands
├── worker/
│   ├── __init__.py
│   ├── celery_app.py        # Celery configuration
│   └── tasks.py             # process_audio task
├── db/
│   ├── __init__.py
│   ├── models.py            # Prompt SQLAlchemy model
│   └── database.py          # Engine, SessionLocal, init
├── shared/
│   ├── __init__.py
│   ├── config.py            # Settings (pydantic-settings)
│   └── schemas.py           # Pydantic request/response models
├── tests/
│   ├── __init__.py
│   ├── test_api.py          # API endpoint tests
│   ├── test_worker.py       # Celery task tests
│   └── conftest.py          # Pytest fixtures
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

### Task 1: Project Setup and Dependencies

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`

- [ ] **Step 1: Create requirements.txt**

```txt
fastapi==0.109.0
uvicorn[standard]==0.27.0
python-telegram-bot==20.8
celery==5.3.6
redis==5.0.1
sqlalchemy==2.0.25
alembic==1.13.1
pydantic-settings==2.1.0
openai-whisper==20231117
google-generativeai==0.3.2
pytest==8.0.0
pytest-asyncio==0.23.4
httpx==0.26.0
requests==2.31.0
```

- [ ] **Step 2: Create .env.example**

```bash
TELEGRAM_BOT_TOKEN=your_token_here
GEMINI_API_KEY=your_key_here
API_TOKEN=generate_random_string_here
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=sqlite:///./recall.db
WHISPER_DEVICE=cpu
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt .env.example
git commit -m "chore: add dependencies and env template"
```

---

### Task 2: Shared Configuration and Schemas

**Files:**
- Create: `shared/__init__.py`
- Create: `shared/config.py`
- Create: `shared/schemas.py`

- [ ] **Step 1: Write config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    gemini_api_key: str
    api_token: str
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "sqlite:///./recall.db"
    whisper_device: str = "cpu"

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Write schemas.py**

```python
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class TranscribeRequest(BaseModel):
    audio_url: str
    session_id: str


class TranscribeResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    prompt_id: Optional[int] = None
    status: str  # pending, processing, completed, failed
    features: Optional[List[str]] = None
    decisions: Optional[List[str]] = None
    next_steps: Optional[List[str]] = None
    blockers: Optional[List[str]] = None
    raw_summary: Optional[str] = None
    error: Optional[str] = None


class ChallengeRequest(BaseModel):
    prompt_id: int


class ChallengeResponse(BaseModel):
    challenges: List[str]


class PromptResponse(BaseModel):
    id: int
    session_id: str
    features: List[str]
    decisions: List[str]
    next_steps: List[str]
    blockers: List[str]
    raw_summary: str
    created_at: datetime
    challenges: Optional[List[str]] = None
```

- [ ] **Step 3: Commit**

```bash
git add shared/
git commit -m "feat: add shared config and schemas"
```

---

### Task 3: Database Models

**Files:**
- Create: `db/__init__.py`
- Create: `db/models.py`
- Create: `db/database.py`

- [ ] **Step 1: Write models.py**

```python
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(255), index=True, nullable=False)
    features = Column(Text, default="[]")  # JSON list
    decisions = Column(Text, default="[]")
    next_steps = Column(Text, default="[]")
    blockers = Column(Text, default="[]")
    raw_summary = Column(Text, default="")
    challenges = Column(Text, nullable=True)  # JSON list
    created_at = Column(DateTime, default=datetime.utcnow)

    def get_features(self) -> list:
        return json.loads(self.features)

    def set_features(self, features: list):
        self.features = json.dumps(features)

    def get_decisions(self) -> list:
        return json.loads(self.decisions)

    def set_decisions(self, decisions: list):
        self.decisions = json.dumps(decisions)

    def get_next_steps(self) -> list:
        return json.loads(self.next_steps)

    def set_next_steps(self, next_steps: list):
        self.next_steps = json.dumps(next_steps)

    def get_blockers(self) -> list:
        return json.loads(self.blockers)

    def set_blockers(self, blockers: list):
        self.blockers = json.dumps(blockers)

    def get_challenges(self) -> list:
        return json.loads(self.challenges) if self.challenges else []

    def set_challenges(self, challenges: list):
        self.challenges = json.dumps(challenges) if challenges else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "features": self.get_features(),
            "decisions": self.get_decisions(),
            "next_steps": self.get_next_steps(),
            "blockers": self.get_blockers(),
            "raw_summary": self.raw_summary,
            "challenges": self.get_challenges(),
            "created_at": self.created_at.isoformat(),
        }
```

- [ ] **Step 2: Write database.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from shared.config import settings
from db.models import Base

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 3: Commit**

```bash
git add db/
git commit -m "feat: add database models and connection"
```

---

### Task 4: Celery Worker Setup

**Files:**
- Create: `worker/__init__.py`
- Create: `worker/celery_app.py`
- Create: `worker/tasks.py`

- [ ] **Step 1: Write celery_app.py**

```python
from celery import Celery
from shared.config import settings

celery_app = Celery(
    "recall_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["worker.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    result_expires=3600,  # 1 hour
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
```

- [ ] **Step 2: Write tasks.py (skeleton)**

```python
import os
import tempfile
from celery import Task
from worker.celery_app import celery_app
from shared.config import settings


class DatabaseTask(Task):
    """Task that has access to database"""
    _db = None

    @property
    def db(self):
        if self._db is None:
            from db.database import SessionLocal
            self._db = SessionLocal()
        return self._db


@celery_app.task(bind=True, base=DatabaseTask, max_retries=3)
def process_audio(self, audio_path: str, session_id: str):
    """Transcribe audio and generate dev brief"""
    try:
        # Step 1: Transcribe with Whisper
        # Step 2: Call Gemini API to extract structured brief
        # Step 3: Save to database
        # Step 4: Clean up temp file
        pass
    except Exception as exc:
        # Clean up temp file on failure
        if os.path.exists(audio_path):
            os.remove(audio_path)
        raise self.retry(exc=exc, countdown=60)
```

- [ ] **Step 3: Commit**

```bash
git add worker/
git commit -m "feat: add celery worker skeleton"
```

---

### Task 5: Whisper Integration

**Files:**
- Modify: `worker/tasks.py`

- [ ] **Step 1: Add Whisper import and transcription logic**

```python
import whisper

# Load model once at module level
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = whisper.load_model("base").to(settings.whisper_device)
    return _whisper_model


@celery_app.task(bind=True, base=DatabaseTask, max_retries=3)
def process_audio(self, audio_path: str, session_id: str):
    """Transcribe audio and generate dev brief"""
    try:
        # Transcribe
        model = get_whisper_model()
        result = model.transcribe(audio_path)
        transcript = result["text"]

        # Clean up audio file
        if os.path.exists(audio_path):
            os.remove(audio_path)

        return {"transcript": transcript, "session_id": session_id}

    except Exception as exc:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        raise self.retry(exc=exc, countdown=60)
```

- [ ] **Step 2: Commit**

```bash
git add worker/tasks.py
git commit -m "feat: integrate Whisper transcription"
```

---

### Task 6: Gemini API Integration

**Files:**
- Modify: `worker/tasks.py`

- [ ] **Step 1: Add Gemini API call**

```python
import google.generativeai as genai

genai.configure(api_key=settings.gemini_api_key)


SYSTEM_PROMPT = """You are an AI teammate helping developers during hackathons and fast-paced development.

Given a transcript of a conversation, extract:
1. Features being discussed (as a list)
2. Decisions made (as a list)
3. Next steps/action items (as a list)
4. Blockers or dependencies (as a list)
5. A one-line summary of what is being built
6. 2-3 sentences of additional context

Respond in JSON format:
{
  "building": "...",
  "features": ["...", "..."],
  "decisions": ["...", "..."],
  "next_steps": ["...", "..."],
  "blockers": ["...", "..."],
  "context": "..."
}"""


@celery_app.task(bind=True, base=DatabaseTask, max_retries=3)
def process_audio(self, audio_path: str, session_id: str):
    """Transcribe audio and generate dev brief"""
    from db.models import Prompt

    try:
        # Transcribe
        model = get_whisper_model()
        result = model.transcribe(audio_path)
        transcript = result["text"]

        # Clean up audio file
        if os.path.exists(audio_path):
            os.remove(audio_path)

        # Call Gemini API
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(
            f"{SYSTEM_PROMPT}\n\nTranscript:\n{transcript}"
        )

        # Parse JSON response
        import json
        content = response.text
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        parsed = json.loads(content)

        # Save to database
        prompt = Prompt(session_id=session_id)
        prompt.set_features(parsed.get("features", []))
        prompt.set_decisions(parsed.get("decisions", []))
        prompt.set_next_steps(parsed.get("next_steps", []))
        prompt.set_blockers(parsed.get("blockers", []))
        prompt.raw_summary = f"Building: {parsed.get('building', '')}\n\nContext: {parsed.get('context', '')}"

        self.db.add(prompt)
        self.db.commit()
        self.db.refresh(prompt)

        return {"prompt_id": prompt.id, "status": "completed"}

    except Exception as exc:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        raise self.retry(exc=exc, countdown=60)
```

- [ ] **Step 2: Commit**

```bash
git add worker/tasks.py
git commit -m "feat: integrate Gemini API for brief extraction"
```

---

### Task 7: Challenge Generation Task

**Files:**
- Modify: `worker/tasks.py`

- [ ] **Step 1: Add challenge task**

```python
CHALLENGE_PROMPT = """You are an AI teammate helping during hackathons. Given a project brief, generate 2-3 probing questions that challenge assumptions or surface things that might have been missed.

Focus on:
- Technical feasibility concerns
- User experience gaps
- Security or edge cases
- Scope creep risks

Respond in JSON format:
{
  "challenges": ["question 1", "question 2", "question 3"]
}"""


@celery_app.task(bind=True, base=DatabaseTask, max_retries=3)
def generate_challenges(self, prompt_id: int):
    """Generate probing questions for a prompt"""
    from db.models import Prompt

    try:
        prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        if not prompt:
            raise ValueError(f"Prompt {prompt_id} not found")

        # Build brief from stored data
        features = "\n- ".join(prompt.get_features()) if prompt.get_features() else "None"
        decisions = "\n- ".join(prompt.get_decisions()) if prompt.get_decisions() else "None"
        next_steps = "\n- ".join(prompt.get_next_steps()) if prompt.get_next_steps() else "None"
        blockers = "\n- ".join(prompt.get_blockers()) if prompt.get_blockers() else "None"

        brief = f"""Building: {prompt.raw_summary}

Features:
- {features}

Decisions:
- {decisions}

Next Steps:
- {next_steps}

Blockers:
- {blockers}"""

        # Call Gemini API
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(
            f"{CHALLENGE_PROMPT}\n\nProject Brief:\n{brief}"
        )

        # Parse JSON response
        import json
        content = response.text
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        parsed = json.loads(content)
        challenges = parsed.get("challenges", [])

        # Update prompt
        prompt.set_challenges(challenges)
        self.db.commit()

        return {"challenges": challenges}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
```

- [ ] **Step 2: Commit**

```bash
git add worker/tasks.py
git commit -m "feat: add challenge generation task using Gemini"
```


---

### Task 8: API Router - Transcribe

**Files:**
- Create: `api/__init__.py`
- Create: `api/deps.py`
- Create: `api/routers/__init__.py`
- Create: `api/routers/transcribe.py`

- [ ] **Step 1: Write deps.py**

```python
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from db.database import get_db
from shared.config import settings


def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ")[1]
    if token != settings.api_token:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token


def get_database(db: Session = Depends(get_db)):
    return db
```

- [ ] **Step 2: Write transcribe.py**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.deps import verify_token, get_database
from shared.schemas import TranscribeRequest, TranscribeResponse, JobStatusResponse
from worker.tasks import process_audio
from worker.celery_app import celery_app
from db.models import Prompt

router = APIRouter()

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


@router.post("/transcribe", response_model=TranscribeResponse)
def create_transcription_job(
    request: TranscribeRequest,
    token: str = Depends(verify_token)
):
    """Queue audio file for transcription"""
    import requests
    import tempfile
    import os

    # Download audio file
    response = requests.get(request.audio_url, timeout=30, stream=True)
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Could not download audio")

    # Check file size
    content_length = response.headers.get('content-length')
    if content_length and int(content_length) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")

    # Ensure temp directory exists
    import os
    os.makedirs("/tmp/recall/audio", exist_ok=True)

    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg", dir="/tmp/recall/audio") as tmp:
        for chunk in response.iter_content(chunk_size=8192):
            tmp.write(chunk)
        audio_path = tmp.name

    # Queue job
    task = process_audio.delay(audio_path, request.session_id)

    return TranscribeResponse(job_id=task.id)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database)
):
    """Get job status and result"""
    from celery.result import AsyncResult

    task = AsyncResult(job_id, app=celery_app)

    if task.state == "PENDING":
        return JobStatusResponse(job_id=job_id, status="pending")
    elif task.state in ("STARTED", "PROGRESS"):
        return JobStatusResponse(job_id=job_id, status="processing")
    elif task.state == "SUCCESS":
        result = task.result
        if result and result.get("prompt_id"):
            prompt = db.query(Prompt).filter(Prompt.id == result["prompt_id"]).first()
            if prompt:
                return JobStatusResponse(
                    job_id=job_id,
                    prompt_id=prompt.id,
                    status="completed",
                    features=prompt.get_features(),
                    decisions=prompt.get_decisions(),
                    next_steps=prompt.get_next_steps(),
                    blockers=prompt.get_blockers(),
                    raw_summary=prompt.raw_summary
                )
        return JobStatusResponse(job_id=job_id, status="completed")
    else:
        error_msg = str(task.result) if task.result else "Unknown error"
        return JobStatusResponse(job_id=job_id, status="failed", error=error_msg)


@router.get("/history")
def get_history(
    session_id: str,
    limit: int = 5,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database)
):
    """Get recent prompts for a session"""
    prompts = db.query(Prompt).filter(
        Prompt.session_id == session_id
    ).order_by(Prompt.created_at.desc()).limit(limit).all()

    return {"prompts": [p.to_dict() for p in prompts]}


@router.get("/prompts/{prompt_id}")
def get_prompt(
    prompt_id: int,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database)
):
    """Get a specific prompt by ID"""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt.to_dict()
```

- [ ] **Step 3: Commit**

```bash
git add api/deps.py api/routers/transcribe.py
git commit -m "feat: add transcribe API endpoints"
```

---

### Task 9: API Router - Challenge

**Files:**
- Create: `api/routers/challenge.py`

- [ ] **Step 1: Write challenge.py**

```python
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.deps import verify_token, get_database
from shared.schemas import ChallengeRequest, ChallengeResponse
from worker.tasks import generate_challenges
from db.models import Prompt

router = APIRouter()


@router.post("/challenge", response_model=ChallengeResponse)
def create_challenge(
    request: ChallengeRequest,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database)
):
    """Generate probing questions for a prompt"""
    prompt = db.query(Prompt).filter(Prompt.id == request.prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # If challenges already exist, return them
    existing = prompt.get_challenges()
    if existing:
        return ChallengeResponse(challenges=existing)

    # Generate challenges synchronously (fast operation)
    from celery.result import EagerResult
    task = generate_challenges.delay(request.prompt_id)
    result = task.get(timeout=30)

    return ChallengeResponse(challenges=result.get("challenges", []))
```

- [ ] **Step 2: Commit**

```bash
git add api/routers/challenge.py
git commit -m "feat: add challenge API endpoint"
```

---

### Task 10: FastAPI Main App

**Files:**
- Create: `api/main.py`

- [ ] **Step 1: Write main.py**

```python
from fastapi import FastAPI
from api.routers import transcribe, challenge
from db.database import init_db

app = FastAPI(title="RECALL API", version="0.1.0")

# Initialize database on startup
@app.on_event("startup")
def startup():
    init_db()

# Health check
@app.get("/health")
def health_check():
    return {"status": "ok"}

# Include routers
app.include_router(transcribe.router, prefix="/api/v1")
app.include_router(challenge.router, prefix="/api/v1")
```

- [ ] **Step 2: Update router __init__.py exports**

Not needed — routers are imported directly.

- [ ] **Step 3: Commit**

```bash
git add api/main.py
git commit -m "feat: add FastAPI main application"
```

---

### Task 11: Telegram Bot - Setup

**Files:**
- Create: `bot/__init__.py`
- Create: `bot/handlers.py`
- Create: `bot/main.py`

- [ ] **Step 1: Write handlers.py (skeleton)**

```python
from telegram import Update
from telegram.ext import ContextTypes


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages"""
    await update.message.reply_text("Received voice message, processing...")


async def challenge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /challenge command"""
    await update.message.reply_text("Challenge feature coming soon...")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command"""
    await update.message.reply_text("History feature coming soon...")


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /get command"""
    await update.message.reply_text("Get feature coming soon...")
```

- [ ] **Step 2: Write main.py**

```python
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from shared.config import settings
from bot.handlers import voice_handler, challenge_command, history_command, get_command


def main():
    application = Application.builder().token(settings.telegram_bot_token).build()

    # Command handlers
    application.add_handler(CommandHandler("challenge", challenge_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("get", get_command))

    # Voice message handler
    application.add_handler(MessageHandler(filters.VOICE, voice_handler))

    # Start polling with 1 second interval and 30 second timeout
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        poll_interval=1.0,
        timeout=30
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add bot/
git commit -m "feat: add telegram bot skeleton"
```

---

### Task 12: Telegram Bot - Voice Handler

**Files:**
- Modify: `bot/handlers.py`

- [ ] **Step 1: Implement voice_handler**

```python
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from shared.config import settings

API_BASE_URL = "http://localhost:8000/api/v1"


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages"""
    # Download voice file
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    await update.message.reply_text("🎧 Transcribing...")

    # Send to API
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE_URL}/transcribe",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            json={
                "audio_url": file.file_path,
                "session_id": str(update.effective_chat.id)
            },
            timeout=30.0
        )

        if response.status_code != 200:
            await update.message.reply_text("❌ Failed to queue transcription")
            return

        job_id = response.json()["job_id"]

        # Poll for result
        import asyncio
        for _ in range(30):  # 30 seconds max
            await asyncio.sleep(1)

            result_response = await client.get(
                f"{API_BASE_URL}/jobs/{job_id}",
                headers={"Authorization": f"Bearer {settings.api_token}"},
                timeout=10.0
            )

            if result_response.status_code != 200:
                continue

            result = result_response.json()

            if result["status"] == "completed":
                # Format response
                msg = format_prompt(result)
                await update.message.reply_text(msg, parse_mode="Markdown")
                return
            elif result["status"] == "failed":
                await update.message.reply_text("❌ Transcription failed")
                return

        await update.message.reply_text("⏱️ Processing taking longer than expected. Use /history to check status.")


def format_prompt(result: dict) -> str:
    """Format prompt result for Telegram"""
    lines = []

    if result.get("raw_summary"):
        lines.append(f"*{result['raw_summary'].split(chr(10))[0]}*")  # Building line
        lines.append("")

    if result.get("features"):
        lines.append("*Features:*")
        for f in result["features"]:
            lines.append(f"• {f}")
        lines.append("")

    if result.get("decisions"):
        lines.append("*Decisions:*")
        for d in result["decisions"]:
            lines.append(f"• {d}")
        lines.append("")

    if result.get("next_steps"):
        lines.append("*Next:*")
        for s in result["next_steps"]:
            lines.append(f"☐ {s}")
        lines.append("")

    if result.get("blockers"):
        lines.append("*Blockers:*")
        for b in result["blockers"]:
            lines.append(f"⚠️ {b}")
        lines.append("")

    if result.get("raw_summary") and "\n" in result["raw_summary"]:
        context = result["raw_summary"].split("\n\n")[-1]
        lines.append(f"_{context}_")

    return "\n".join(lines)
```

- [ ] **Step 2: Commit**

```bash
git add bot/handlers.py
git commit -m "feat: implement voice message handler"
```

---

### Task 13: Telegram Bot - Commands

**Files:**
- Modify: `bot/handlers.py`

- [ ] **Step 1: Implement commands**

```python
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from shared.config import settings

API_BASE_URL = "http://localhost:8000/api/v1"


async def challenge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /challenge command - generate questions for last prompt"""
    chat_id = str(update.effective_chat.id)

    async with httpx.AsyncClient() as client:
        # First get history to find latest prompt
        history_response = await client.get(
            f"{API_BASE_URL}/history",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            params={"session_id": chat_id, "limit": 1},
            timeout=10.0
        )

        if history_response.status_code != 200:
            await update.message.reply_text("❌ Could not fetch history")
            return

        history = history_response.json()
        if not history.get("prompts"):
            await update.message.reply_text("No prompts found. Send a voice message first!")
            return

        latest_prompt = history["prompts"][0]
        prompt_id = latest_prompt["id"]

        await update.message.reply_text("🤔 Generating challenges...")

        response = await client.post(
            f"{API_BASE_URL}/challenge",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            json={"prompt_id": prompt_id},
            timeout=30.0
        )

        if response.status_code != 200:
            await update.message.reply_text("❌ Failed to generate challenges")
            return

        challenges = response.json()["challenges"]

        lines = ["*Challenges:*", ""]
        for i, c in enumerate(challenges, 1):
            lines.append(f"{i}. {c}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command - show recent prompts"""
    chat_id = str(update.effective_chat.id)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/history",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            params={"session_id": chat_id, "limit": 5},
            timeout=10.0
        )

        if response.status_code != 200:
            await update.message.reply_text("❌ Could not fetch history")
            return

        prompts = response.json().get("prompts", [])

        if not prompts:
            await update.message.reply_text("No prompts yet. Send a voice message!")
            return

        lines = ["*Recent prompts:*", ""]
        for p in prompts:
            summary = p.get("raw_summary", "").split("\n")[0] if p.get("raw_summary") else "Untitled"
            lines.append(f"`{p['id']}`: {summary[:50]}...")

        lines.append("")
        lines.append("Use `/get {id}` to view full prompt")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /get command - retrieve specific prompt"""
    if not context.args:
        await update.message.reply_text("Usage: `/get {prompt_id}`")
        return

    try:
        prompt_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid prompt ID. Use `/get {number}`")
        return

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/prompts/{prompt_id}",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            timeout=10.0
        )

        if response.status_code == 404:
            await update.message.reply_text("Prompt not found.")
            return
        elif response.status_code != 200:
            await update.message.reply_text("❌ Failed to fetch prompt")
            return

        prompt = response.json()
        msg = format_prompt(prompt)
        await update.message.reply_text(msg, parse_mode="Markdown")

    finally:
        db.close()
```

- [ ] **Step 2: Commit**

```bash
git add bot/handlers.py
git commit -m "feat: implement bot commands (/challenge, /history, /get)"
```

---

### Task 14: Docker Setup

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Write Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Whisper
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Whisper model during build
RUN python -c "import whisper; whisper.load_model('base')"

# Copy application code
COPY . .

# Default command (overridden in docker-compose)
CMD ["python", "-m", "api.main"]
```

- [ ] **Step 2: Write docker-compose.yml**

```yaml
version: "3.8"

services:
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  api:
    build: .
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
    ports:
      - "8000:8000"
    volumes:
      - ./:/app
      - audio_temp:/tmp/recall/audio
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=sqlite:///./data/recall.db
    depends_on:
      - redis

  worker:
    build: .
    command: celery -A worker.celery_app worker --loglevel=info --concurrency=2
    volumes:
      - ./:/app
      - audio_temp:/tmp/recall/audio
      - ./data:/app/data
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=sqlite:///./data/recall.db
    depends_on:
      - redis

  bot:
    build: .
    command: python -m bot.main
    volumes:
      - ./:/app
      - ./data:/app/data
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=sqlite:///./data/recall.db
    depends_on:
      - api
      - redis

volumes:
  redis_data:
  audio_temp:
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "chore: add Docker configuration"
```

---

### Task 15: Tests

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write conftest.py**

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base
from api.main import app
from shared.config import settings

# Use in-memory database for tests
TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def api_token():
    return settings.api_token
```

- [ ] **Step 2: Write test_api.py**

```python
import pytest
from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_transcribe_requires_auth(client: TestClient):
    response = client.post("/api/v1/transcribe", json={"audio_url": "http://test", "session_id": "123"})
    assert response.status_code == 401


def test_transcribe_invalid_token(client: TestClient):
    response = client.post(
        "/api/v1/transcribe",
        json={"audio_url": "http://test", "session_id": "123"},
        headers={"Authorization": "Bearer invalid_token"}
    )
    assert response.status_code == 401
```

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: add initial API tests"
```

---

### Task 16: Final Integration and README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README.md**

```markdown
# RECALL

Voice-to-dev-brief for hackathons. Send a voice message, get a structured summary.

## Quick Start

1. Copy `.env.example` to `.env` and fill in your tokens
2. Build and run:
   ```bash
   docker-compose up --build
   ```

## Development

### Run API only:
```bash
uvicorn api.main:app --reload
```

### Run Celery worker:
```bash
celery -A worker.celery_app worker --loglevel=info
```

### Run Bot:
```bash
python -m bot.main
```

## Telegram Commands

- Send voice message → Get structured brief
- `/challenge` → Get probing questions
- `/history` → List recent prompts
- `/get {id}` → View specific prompt
```

- [ ] **Step 2: Final commit**

```bash
git add README.md
git commit -m "docs: add README"
```

---

## Summary

16 tasks to build RECALL:
1. Project setup (requirements, .env)
2-3. Shared code (config, schemas, database)
4-7. Worker (Celery, Whisper, Claude, challenges)
8-10. API (auth, transcribe, challenge endpoints, main app)
11-13. Bot (setup, voice handler, commands)
14. Docker configuration
15. Tests
16. README

**Estimated time:** 2-3 hours for a skilled developer working sequentially.
