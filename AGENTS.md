# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

**Recall** is a Telegram bot that transcribes voice messages and produces structured development briefs (features, decisions, next steps, blockers) using Groq's Whisper and Llama 3.3 70B APIs. Users can also request probing "challenge" questions against their latest brief.

## Common Commands

**Start all services (primary dev workflow):**
```bash
docker-compose up --build
```

**Run tests** (requires a valid `.env` file since `shared/config.py` loads it at import time):
```bash
pytest tests/
```

**Run a single test:**
```bash
pytest tests/test_api.py::test_health_check
```

**Run services individually (outside Docker):**
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
celery -A worker.celery_app worker --loglevel=info --concurrency=1
python -m bot.main
```

## Environment Setup

Copy `.env.example` to `.env` and fill in:
- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `GROQ_API_KEY` — from console.groq.com (note: `.env.example` incorrectly names this `GEMINI_API_KEY`; the actual key expected by `shared/config.py` is `GROQ_API_KEY`)
- `API_TOKEN` — any random secret string for internal auth between the bot and API

## Architecture

Four services communicate in a unidirectional pipeline:

```
Telegram → Bot → API → Redis → Worker → Groq API
                                      → SQLite DB → Bot (via polling)
```

- **`bot/`** — `python-telegram-bot` polling loop. Registers handlers in `bot/main.py`, logic in `bot/handlers.py`. Makes HTTP calls to the FastAPI API using `httpx`. The bot polls job status synchronously (up to 30 × 1s iterations) after submitting a transcription job.
- **`api/`** — FastAPI server. Receives requests from the bot, downloads audio from Telegram's CDN, queues Celery tasks, and serves job status/history. All routes require a `Bearer` token (validated in `api/deps.py`). Routes are split across `api/routers/transcribe.py` and `api/routers/challenge.py`.
- **`worker/`** — Celery worker (`celery_app.py` configures the app; `tasks.py` defines tasks). The `process_audio` task handles transcription (Groq Whisper `whisper-large-v3`, with chunking for audio > 10 minutes) then summarization (Groq Llama 3.3 70B, JSON-mode). `generate_challenges` takes an existing prompt and produces 2–3 probing questions. Both tasks use `DatabaseTask` base class to lazily hold a DB session.
- **`shared/`** — `config.py` provides a singleton `settings` object (pydantic-settings, reads from `.env`). `schemas.py` defines all Pydantic request/response models shared between the API and bot.
- **`db/`** — SQLAlchemy setup and a single `Prompt` model. List fields (`features`, `decisions`, `next_steps`, `blockers`, `challenges`) are stored as JSON text columns with `get_*`/`set_*` helper methods. `session_id` is the Telegram chat ID.

## Key Design Decisions

- **No Alembic migrations in use** — `init_db()` calls `Base.metadata.create_all()` on every API startup, so schema is managed via model changes directly.
- **Tests use in-memory SQLite** — `conftest.py` overrides the DB for every test function; no real DB or running services are needed for the test suite.
- **`API_TOKEN` is the only auth layer** between the bot and API; it is passed as a `Bearer` header on every internal request.
- The Dockerfile installs `openai-whisper` (and pre-downloads the `base` model), but the worker currently uses the Groq API for transcription — this is likely a leftover from an earlier design.
