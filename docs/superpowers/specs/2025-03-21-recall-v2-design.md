# Recall — Design Spec v2

**Date:** 2026-03-22
**Version:** v2
**Status:** Draft

---

## Overview

v2 moves Recall from a single-user voice transcriber to a long-term
thinking companion. Core additions: memory layer, semantic search,
collaborators, speaker diarization, smart context window, and new commands.

---

## Architecture
```
┌─────────────┐     ┌─────────────┐     ┌──────────────────────────┐
│  Telegram   │────▶│  FastAPI    │────▶│      Celery Worker       │
│    Bot      │◄────│   Server    │◄────│  Groq Whisper            │
└─────────────┘     └──────┬──────┘     │  Groq Llama 3.3 70B      │
                           │            │  Nomic Embed (local)      │
                    ┌──────┴──────┐     │  pyannote.audio           │
                    │   Alembic   │     └──────────────────────────┘
                    │ (Migrations)│
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │   SQLite    │
                    └─────────────┘
```

---

## Data Model
```python
class User:
    id: int (PK)
    telegram_id: str (Unique)
    username: str
    created_at: datetime

class Session:
    id: int (PK)
    owner_id: int (FK → User)
    collaborator_id: int (FK → User, Optional)
    created_at: datetime

class Prompt (Updated):
    id: int (PK)
    user_id: int (FK → User)
    session_id: int (FK → Session)
    transcript: str
    raw_summary: str
    features: str (JSON)
    decisions: str (JSON)
    next_steps: str (JSON)
    blockers: str (JSON)
    challenges: str (JSON)
    tags: str (JSON)
    speaker_attribution: str (JSON)
    embedding: str (JSON — Nomic Embed vector)
    created_at: datetime

class CollaboratorInvite:
    id: int (PK)
    session_id: int (FK → Session)
    inviter_id: int (FK → User)
    invitee_telegram_username: str
    status: str  # pending / accepted / declined
    created_at: datetime
```

---

## New Commands

| Command | Description |
|---------|-------------|
| `/prompt` | Ask 2-3 questions then generate context-aware vibe coding prompt |
| `/brainstorm` | Develop latest idea — features, pivots, similar products |
| `/summary` | Weekly digest grouped by tag |
| `/search [keyword]` | Semantic search across all briefs via Nomic Embed |
| `/evolution` | Timeline of how an idea changed across sessions |
| `/ideas [tag]` | Filter briefs by auto-generated tag |
| `/add @username` | Invite a collaborator to your session |
| `/challenge` | (existing) Probing questions on latest brief |
| `/history` | (existing) 5 most recent briefs |
| `/get {id}` | (existing) Retrieve specific brief |

---

## Key Features

### Memory Layer
Recent brief history passed as context to LLM on every request.
Surfaces connections — "you've discussed this 3 times, here's how
your thinking has changed."

### Smart Context Window
Follow-up voice note within 30 minutes updates existing brief instead
of creating a new one. Applies to solo and collaborative sessions.

### Speaker Diarization
Multi-person recordings split by speaker. Attribution linked to
Telegram usernames when collaborators are active. Powered by
pyannote.audio.

### Auto-tagging
LLM generates domain tags (edtech, fintech, hardware, etc.) as part
of brief extraction. No manual input.

### Semantic Search
Nomic Embed Text runs locally. Every brief gets an embedding on
creation. Search uses cosine similarity — finds meaning, not just
keywords.

### Collaborators
/add @username sends invite. Once accepted, shared session space.
Voice notes from either user attributed by username. Both receive
output on brief completion. Smart context window applies to shared
sessions too.

---

## Stack

| Component | Technology |
|-----------|------------|
| Bot | python-telegram-bot |
| API | FastAPI |
| Task queue | Celery + Redis (persistent) |
| Transcription | Groq Whisper API |
| LLM | Groq Llama 3.3 70B |
| Embeddings | Nomic Embed Text (local) |
| Diarization | pyannote.audio |
| Database | SQLite + SQLAlchemy |
| Migrations | Alembic |

---

## Out of Scope

Web app, mobile app, Notion export, OCR, public sharing, payments,
fine-tuning. These are v3 territory.