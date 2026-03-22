# RECALL Design Spec

**Date:** 2025-03-20
**Version:** P1 (Telegram Bot)
**Purpose:** Voice-to-dev-brief for hackathons and fast-paced development

---

## Overview

RECALL listens to voice conversations, transcribes them with local Whisper, and extracts structured development briefs using Claude API. The output is a copy-pasteable format with features, decisions, next steps, and blockers.

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│  Telegram   │────▶│  FastAPI    │────▶│  Celery Worker  │
│    Bot      │◄────│   Server    │◄────│  (Whisper +     │
└─────────────┘     └──────┬──────┘     │   Claude API)   │
                           │            └─────────────────┘
                           ▼
                    ┌─────────────┐
                    │   SQLite    │
                    │  (prompts)  │
                    └─────────────┘
```

---

## Data Model

```python
class Prompt:
    id: int                    # Primary key
    session_id: str            # Telegram chat ID
    features: list[str]        # Extracted features
    decisions: list[str]        # Key decisions made
    next_steps: list[str]       # Action items
    blockers: list[str]         # Blockers/dependencies
    raw_summary: str            # Full text fallback
    created_at: datetime
    challenges: list[str]       # Generated on /challenge
```

---

## Output Format

```
Building: [one-liner from conversation]

Features:
- feature 1
- feature 2

Decisions:
- decision 1
- decision 2

Next:
- [ ] action item 1
- [ ] action item 2

Blockers:
- blocker 1

Context: [2-3 sentences of extra context]
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/transcribe` | Queue audio file, return job_id |
| GET | `/jobs/{id}` | Check status, get result |
| POST | `/challenge` | Generate questions for prompt_id |

---

## Commands

| Command | Description |
|---------|-------------|
| (voice message) | Transcribe and summarize |
| `/challenge` | Get AI probing questions |
| `/history` | List recent prompts |
| `/get {id}` | Retrieve specific prompt |

---

## Tech Stack

- **Bot:** python-telegram-bot
- **API:** FastAPI + Uvicorn
- **Queue:** Celery + Redis
- **Transcription:** openai-whisper (local)
- **AI:** Claude API (anthropic SDK)
- **DB:** SQLite + SQLAlchemy

---

## Environment Variables

```
TELEGRAM_BOT_TOKEN=
ANTHROPIC_API_KEY=
API_TOKEN=                    # Internal API auth
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=sqlite:///./recall.db
WHISPER_DEVICE=cpu            # or 'cuda' for GPU
```

---

## File Handling

- **Temp storage:** `/tmp/recall/audio/{job_id}.ogg` (cleaned up after processing)
- **Limits:** 20MB max file size, 5 minutes max duration
- **Cleanup:** Celery task deletes temp files after successful transcription

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Whisper fails | Return error: "Could not transcribe audio" |
| Claude API fails | Retry 2x with exponential backoff, then "AI service unavailable" |
| Rate limited | Queue with delay, notify user "Processing delayed" |
| File too large | Reject immediately with size limit message |

## Telegram Configuration

- **Mode:** Long-polling (simpler for P1, no webhook URL needed)
- **Polling interval:** 1 second
- **Timeout:** 30 seconds

## Celery Configuration

- **Broker:** Redis (for task queue)
- **Result backend:** Redis (results expire after 1 hour)
- **Task acks:** Late acknowledgment (requeue if worker dies)
- **Max retries:** 3 for transcription tasks

## API Authentication

- **Internal token:** `API_TOKEN` env var
- **Header:** `Authorization: Bearer {token}`
- **Bot-to-API:** Uses internal token (same network)

## Whisper Model

- **Model:** `base` (74MB, ~5s transcription for 60s audio on CPU)
- **Language:** Auto-detect
- **Device:** CPU (GPU optional via env var)

## Database

- **Migrations:** `create_all()` on startup (P1), Alembic for P2
- **Index:** `session_id` indexed for `/history` queries
- **JSON fields:** Store lists as JSON strings in SQLite

## Deployment

- **Container:** Docker + docker-compose (Redis, API, Worker, Bot)
- **Health check:** `GET /health` returns 200
- **Volumes:** `/tmp/recall/audio` (temp), `./data` (SQLite)

## Success Criteria

- Voice message → structured brief in < 30 seconds
- `/challenge` generates relevant probing questions
- SQLite persists prompts across sessions
- Handles concurrent voice messages via queue
