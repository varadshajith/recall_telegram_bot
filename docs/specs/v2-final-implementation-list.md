# Recall v2 — Final Implementation List

**Date:** 2026-03-23  
**Scope:** What is implemented in Recall v2, mapped to the v2 plan tasks.  

This document is the “as-built” checklist for v2.

---

## Task 1 — Database & Migrations (DONE)

- **Alembic added and initialized**
  - `alembic.ini`
  - `alembic/env.py`
  - `alembic/script.py.mako`
- **Initial v2 migration created**
  - `alembic/versions/001_v2_schema.py`
  - Creates new tables: `users`, `sessions`, `collaborator_invites`
  - Creates or upgrades `prompts` to v2 schema (adds: `user_id`, `session_id` FK, `legacy_chat_id`, `transcript`, `tags`, `speaker_attribution`, `embedding`, `created_at`)
  - Includes a **v1 upgrade path** (backfills `User`/`Session` rows from legacy prompt `session_id`)
- **API startup runs DB init**
  - `db/database.py` → `init_db()`
  - `api/main.py` calls `init_db()` on startup

**Data model implemented**
- `db/models.py`: `User`, `Session`, `Prompt`, `CollaboratorInvite`

---

## Task 2 — Timestamps + Auto-tagging (DONE)

- **Timestamps**
  - `Prompt.created_at` exists and is populated
- **Auto-tagging**
  - Worker system prompt requests `tags` in JSON output
  - Stored in `Prompt.tags` (JSON text column)

Where:
- `worker/tasks.py` (`SYSTEM_PROMPT` + prompt persistence)
- `db/models.py` (`tags` + `get_tags()`/`set_tags()`)

---

## Task 3 — Memory Layer (DONE)

- On each ingestion, the worker fetches recent briefs and adds them as context to the LLM prompt.
- **Session-scoped memory** (works for collaborations too).

Where:
- `worker/tasks.py` → `get_recent_briefs()` + `memory_block`

---

## Task 4 — Smart Context Window (DONE)

- If the session has a brief within the last **30 minutes**, the worker updates it instead of creating a new prompt.
- **Session-scoped** (works for collaborations too).

Where:
- `worker/tasks.py` → `get_recent_prompt(..., minutes=30)` + merge path

---

## Task 5 — Semantic Search (DONE)

- **Embeddings**
  - SentenceTransformers model (default: `nomic-ai/nomic-embed-text-v1`) is loaded lazily
  - Each prompt gets an embedding (best-effort; embedding failure does not fail ingestion)
- **Search**
  - `POST /api/v1/search` embeds the query and ranks prompts by cosine similarity
  - Returns top N results (default `limit=3`)
  - **Session-scoped** to sessions the user participates in

Where:
- `worker/tasks.py` → `get_embed_model()`, `embed_text()`, `cosine_similarity()`, embedding persistence
- `api/routers/memory.py` → `POST /search`
- `shared/schemas.py` → `SearchRequest`, `SearchResponse`

---

## Task 6 — New Commands (DONE)

### Implemented API endpoints
- `POST /api/v1/brainstorm`
- `GET /api/v1/summary`
- `GET /api/v1/evolution`
- `GET /api/v1/ideas`
- `POST /api/v1/prompt/start`
- `POST /api/v1/prompt/complete`

Where:
- `api/routers/memory.py`
- `shared/schemas.py` (response models)
- Worker tasks:
  - `worker/tasks.py`: `generate_brainstorm`, `generate_weekly_summary`, `generate_prompt_questions`, `generate_coding_prompt`

### Implemented bot commands
- `/brainstorm`
- `/summary`
- `/search <query>`
- `/evolution`
- `/ideas [tag]`
- `/prompt` (multi-turn flow; `/cancel` fallback)

Where:
- `bot/handlers.py`
- `bot/main.py`

---

## Task 7 — Collaborators (DONE)

### API routes implemented
- `POST /api/v1/collaborators/invite`
- `POST /api/v1/collaborators/respond`
- `GET /api/v1/collaborators/pending`

Where:
- `api/routers/collaborators.py`
- `shared/schemas.py` (`InviteRequest`, `InviteResponse`, `RespondInviteRequest`)

### Shared session semantics implemented (critical v2 behavior)
- Ingestion writes to the most recent session the user participates in.
  - If user is a collaborator in any session, that shared session is preferred.
- `/history` and v2 “memory” endpoints query prompts across all sessions where the user is owner/collaborator.

Where:
- `worker/tasks.py` → `get_or_create_session()` + session-scoped memory/context window
- `api/routers/transcribe.py` → `/history` session-scoped
- `api/routers/memory.py` → session-scoped queries for search/evolution/ideas/latest prompt

### Invite UX in bot
- `/add @username` sends invite request
- If invitee chat_id is known, bot sends inline buttons (accept/decline)

Where:
- `bot/handlers.py` → `add_command()` + `invite_callback()`

---

## Task 8 — Speaker Diarization (DONE, gated)

- Optional diarization via `pyannote.audio` controlled by:
  - `ENABLE_DIARIZATION=true`
  - `HUGGINGFACE_TOKEN=...` (required)
- When diarization is enabled:
  - Audio is diarized → each segment is transcribed → merged with labels
- **Attribution persistence**
  - `Prompt.speaker_attribution` is stored as JSON list of turns
- **Best-effort mapping to Telegram usernames**
  - Dominant diarization label is mapped to the sender username
  - If session has a collaborator, the second-most-dominant label is mapped to collaborator username (when available)
  - Falls back gracefully (labels only or single “SENDER” entry)

Where:
- `shared/config.py` + `.env.example` (feature gates)
- `worker/tasks.py` → `transcribe_with_diarization()` + mapping + `speaker_attribution` building
- `db/models.py` → `get_speaker_attribution()` / `set_speaker_attribution()` + `to_dict()` exposure

---

## Task 9 — BotFather Registration (DONE)

- **README includes `/setcommands` instructions** for v2 command list
- **Optional script** to register commands programmatically:
  - `scripts/register_telegram_commands.py`

Where:
- `README.md`
- `scripts/register_telegram_commands.py`

---

## Verification / Tests (DONE)

- Added v2 coverage for shared-session behavior and new v2 endpoints:
  - history includes shared session prompts
  - search is session-scoped and ranks deterministically (mocked similarity)
  - brainstorm uses latest prompt across sessions (task mocked)
  - collaborator invite/accept updates `Session.collaborator_id`

Where:
- `tests/test_v2_memory_and_collaboration.py`
- `tests/conftest.py`

---

## Notes / Known constraints

- **Diarization mapping is heuristic**: it assumes the dominant diarized speaker is the message sender.
- **Diarization requires Hugging Face model access approval** for `pyannote/speaker-diarization-3.1`.

