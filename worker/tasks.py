import os
import sys
import json
import tempfile
from datetime import datetime, timedelta
from typing import Optional
from celery import Task

# Add project root to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.celery_app import celery_app
from shared.config import settings
from groq import Groq
from pydub import AudioSegment

# Initialize Groq client
client = Groq(api_key=settings.groq_api_key)

# ---------------------------------------------------------------------------
# Lazy singletons for heavy models
# ---------------------------------------------------------------------------
_embed_model = None
_diarization_pipeline = None


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(settings.embed_model, trust_remote_code=True)
    return _embed_model


def get_diarization_pipeline():
    global _diarization_pipeline
    if _diarization_pipeline is None:
        from pyannote.audio import Pipeline
        _diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=settings.huggingface_token,
        )
    return _diarization_pipeline


# ---------------------------------------------------------------------------
# Database task base class
# ---------------------------------------------------------------------------

class DatabaseTask(Task):
    """Task that holds a lazy database session."""
    _db = None

    @property
    def db(self):
        if self._db is None:
            from db.database import SessionLocal
            self._db = SessionLocal()
        return self._db


# ---------------------------------------------------------------------------
# User / Session helpers
# ---------------------------------------------------------------------------

def get_or_create_user(db, telegram_id: str, username: str = ""):
    from db.models import User
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id, username=username or "")
        db.add(user)
        db.commit()
        db.refresh(user)
    elif username and user.username != username:
        user.username = username
        db.commit()
    return user


def get_or_create_session(db, user):
    """
    Return the most recent session the user participates in.

    - If user is an owner, pick the newest session where `owner_id=user.id`
    - If user is a collaborator, pick the newest session where `collaborator_id=user.id`
    - If none exist, create a new solo session where the user is the owner.
    """
    from db.models import Session
    # If the user has been added as a collaborator anywhere, prefer those shared sessions.
    # This prevents accidentally writing to a previously-created solo session.
    session = (
        db.query(Session)
        .filter(Session.collaborator_id == user.id)
        .order_by(Session.created_at.desc())
        .first()
    )
    if not session:
        session = (
            db.query(Session)
            .filter(Session.owner_id == user.id)
            .order_by(Session.created_at.desc())
            .first()
        )
    if not session:
        session = Session(owner_id=user.id)
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def get_recent_prompt(db, session_id: int, minutes: int = 30):
    """Return the most recent prompt for this session within `minutes`."""
    from db.models import Prompt
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    return (
        db.query(Prompt)
        .filter(Prompt.session_id == session_id, Prompt.created_at >= cutoff)
        .order_by(Prompt.created_at.desc())
        .first()
    )


def get_recent_briefs(db, session_id: int, limit: int = 5):
    """Return the last `limit` prompts for this session (for memory context)."""
    from db.models import Prompt
    return (
        db.query(Prompt)
        .filter(Prompt.session_id == session_id)
        .order_by(Prompt.created_at.desc())
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an AI teammate helping developers during hackathons and fast-paced development.

Given a transcript of a conversation, extract:
1. Features being discussed (as a list)
2. Decisions made (as a list)
3. Next steps/action items (as a list)
4. Blockers or dependencies (as a list)
5. A one-line summary of what is being built
6. 2-3 sentences of additional context
7. Domain tags (e.g. fintech, edtech, mobile, api, hardware — pick 1-3 short lowercase tags)

Respond in JSON format:
{
  "building": "...",
  "features": ["...", "..."],
  "decisions": ["...", "..."],
  "next_steps": ["...", "..."],
  "blockers": ["...", "..."],
  "context": "...",
  "tags": ["...", "..."]
}"""


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def clean_list(items):
    """Filter out common LLM placeholder strings like 'n', 'none', 'n/a'."""
    if not items or not isinstance(items, list):
        return []
    return [i for i in items if i and str(i).lower().strip() not in ("n", "none", "n/a")]


def format_brief(prompt) -> str:
    """Format a Prompt object into a short text block for LLM context."""
    features = "\n- ".join(prompt.get_features()) or "None"
    decisions = "\n- ".join(prompt.get_decisions()) or "None"
    next_steps = "\n- ".join(prompt.get_next_steps()) or "None"
    blockers = "\n- ".join(prompt.get_blockers()) or "None"
    tags = ", ".join(prompt.get_tags()) or "none"
    return (
        f"[{prompt.created_at.strftime('%Y-%m-%d')} | tags: {tags}]\n"
        f"{prompt.raw_summary}\n"
        f"Features:\n- {features}\n"
        f"Decisions:\n- {decisions}\n"
        f"Next steps:\n- {next_steps}\n"
        f"Blockers:\n- {blockers}"
    )


def embed_text(text: str) -> list:
    """Generate a Nomic Embed vector for a document string."""
    model = get_embed_model()
    vec = model.encode(f"search_document: {text}", normalize_embeddings=True)
    return vec.tolist()


def cosine_similarity(a: list, b: list) -> float:
    import numpy as np
    a, b = np.array(a), np.array(b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def transcribe_audio_file(audio_path: str) -> str:
    """Transcribe an audio file via Groq Whisper, chunking if > 10 minutes."""
    audio = AudioSegment.from_file(audio_path)
    ten_min_ms = 10 * 60 * 1000
    chunks = [
        audio[i : i + ten_min_ms] for i in range(0, len(audio), ten_min_ms)
    ] if len(audio) > ten_min_ms else [audio]

    parts = []
    for chunk in chunks:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
            chunk.export(tmp.name, format="ogg")
            with open(tmp.name, "rb") as f:
                result = client.audio.transcriptions.create(
                    file=(tmp.name, f.read()),
                    model="whisper-large-v3",
                )
            os.remove(tmp.name)
        parts.append(result.text)
    return " ".join(parts)


def transcribe_with_diarization(audio_path: str) -> tuple[str, list[dict]]:
    """
    Run pyannote speaker diarization then transcribe each segment.
    Returns:
    - transcript text with speaker labels: 'SPEAKER_00: text ...'
    - speaker attribution turns: [{'speaker': 'SPEAKER_00', 'text': '...'}, ...]

    If diarization fails, returns the plain transcript and an empty attribution list.
    """
    try:
        pipeline = get_diarization_pipeline()
        diarization = pipeline(audio_path)
        audio = AudioSegment.from_file(audio_path)
        parts = []
        turns: list[dict] = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            start_ms = int(turn.start * 1000)
            end_ms = int(turn.end * 1000)
            chunk = audio[start_ms:end_ms]
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
                chunk.export(tmp.name, format="ogg")
                with open(tmp.name, "rb") as f:
                    result = client.audio.transcriptions.create(
                        file=(tmp.name, f.read()),
                        model="whisper-large-v3",
                    )
                os.remove(tmp.name)
            parts.append(f"{speaker}: {result.text}")
            turns.append({"speaker": speaker, "text": result.text})
        return "\n".join(parts), turns
    except Exception:
        # Graceful fallback: plain transcription (attribution will be filled by caller)
        return transcribe_audio_file(audio_path), []


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, base=DatabaseTask, max_retries=3)
def process_audio(self, audio_path: str, session_id: str, telegram_username: str = ""):
    """
    Main ingestion pipeline.
    `session_id` is the Telegram chat_id string (used as telegram_id).
    """
    from db.models import Prompt

    try:
        # 1. Resolve user & session
        user = get_or_create_user(self.db, telegram_id=session_id, username=telegram_username)
        db_session = get_or_create_session(self.db, user)

        # 2. Transcribe (with optional diarization) + build attribution
        if settings.enable_diarization:
            transcript_text, speaker_turns = transcribe_with_diarization(audio_path)
            if speaker_turns:
                # Best-effort mapping from diarization labels (SPEAKER_00, ...) to
                # Telegram usernames. We assume the dominant speaker in the audio is
                # the sender of the voice message.
                label_weights = {}
                for t in speaker_turns:
                    label = t.get("speaker")
                    label_weights[label] = label_weights.get(label, 0) + len(t.get("text") or "")
                ordered_labels = sorted(label_weights.keys(), key=lambda l: label_weights.get(l, 0), reverse=True)

                label_to_username = {}
                if telegram_username and ordered_labels:
                    label_to_username[ordered_labels[0]] = telegram_username

                other_username = None
                try:
                    from db.models import User

                    # If this shared session has a collaborator, map the next-dominant
                    # diarization label to their username when possible.
                    if db_session.collaborator_id:
                        if db_session.owner_id == user.id:
                            other_user = self.db.query(User).filter(User.id == db_session.collaborator_id).first()
                        elif db_session.collaborator_id == user.id:
                            other_user = self.db.query(User).filter(User.id == db_session.owner_id).first()
                        else:
                            other_user = None
                        if other_user and other_user.username:
                            other_username = other_user.username
                except Exception:
                    other_username = None

                if other_username and len(ordered_labels) > 1:
                    label_to_username[ordered_labels[1]] = other_username

                speaker_attribution = [
                    {
                        "speaker": t.get("speaker"),
                        "telegram_username": label_to_username.get(t.get("speaker")),
                        "text": t.get("text") or "",
                    }
                    for t in speaker_turns
                ]
            else:
                # Diarization failed: store a single "sender" turn so history is not blank.
                speaker_attribution = [
                    {
                        "speaker": "SENDER",
                        "telegram_username": telegram_username or None,
                        "text": transcript_text,
                    }
                ]
        else:
            transcript_text = transcribe_audio_file(audio_path)
            speaker_attribution = [
                {
                    "speaker": "SENDER",
                    "telegram_username": telegram_username or None,
                    "text": transcript_text,
                }
            ]

        if os.path.exists(audio_path):
            os.remove(audio_path)

        # 3. Memory context: fetch last 5 briefs
        recent = get_recent_briefs(self.db, db_session.id, limit=5)
        memory_block = ""
        if recent:
            memory_block = (
                "\n\nPrevious project context for this user (most recent first):"
                + "".join(f"\n---\n{format_brief(p)}" for p in recent)
                + "\n---\nUse this context to surface connections between ideas."
            )

        # 4. Summarize with Groq Llama
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT + memory_block},
                {"role": "user", "content": f"Transcript:\n{transcript_text}"},
            ],
            response_format={"type": "json_object"},
        )
        parsed = json.loads(completion.choices[0].message.content)

        # 5. Smart context window: update existing brief if within 30 min
        recent_prompt = get_recent_prompt(self.db, db_session.id, minutes=30)
        if recent_prompt:
            # Merge into existing brief
            recent_prompt.transcript = (recent_prompt.transcript or "") + "\n\n" + transcript_text
            recent_prompt.set_features(clean_list(parsed.get("features", [])))
            recent_prompt.set_decisions(clean_list(parsed.get("decisions", [])))
            recent_prompt.set_next_steps(clean_list(parsed.get("next_steps", [])))
            recent_prompt.set_blockers(clean_list(parsed.get("blockers", [])))
            recent_prompt.set_tags(clean_list(parsed.get("tags", [])))
            # Append new attribution to existing turn list.
            existing_attr = recent_prompt.get_speaker_attribution()
            recent_prompt.set_speaker_attribution(existing_attr + speaker_attribution)
            recent_prompt.raw_summary = (
                f"Building: {parsed.get('building', '')}\n\nContext: {parsed.get('context', '')}"
            )
            prompt = recent_prompt
        else:
            # Create new brief
            prompt = Prompt(
                user_id=user.id,
                session_id=db_session.id,
                legacy_chat_id=session_id,
                transcript=transcript_text,
            )
            prompt.set_features(clean_list(parsed.get("features", [])))
            prompt.set_decisions(clean_list(parsed.get("decisions", [])))
            prompt.set_next_steps(clean_list(parsed.get("next_steps", [])))
            prompt.set_blockers(clean_list(parsed.get("blockers", [])))
            prompt.set_tags(clean_list(parsed.get("tags", [])))
            prompt.set_speaker_attribution(speaker_attribution)
            prompt.raw_summary = (
                f"Building: {parsed.get('building', '')}\n\nContext: {parsed.get('context', '')}"
            )
            self.db.add(prompt)

        self.db.commit()
        self.db.refresh(prompt)

        # 6. Generate and store embedding (best-effort — don't fail the task)
        try:
            embed_input = prompt.raw_summary + " " + " ".join(prompt.get_tags())
            prompt.set_embedding(embed_text(embed_input))
            self.db.commit()
        except Exception:
            pass

        return {"prompt_id": prompt.id, "status": "completed"}

    except Exception as exc:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        raise self.retry(exc=exc, countdown=60)


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
    """Generate probing questions for a prompt using Llama."""
    from db.models import Prompt

    try:
        prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        if not prompt:
            raise ValueError(f"Prompt {prompt_id} not found")

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": CHALLENGE_PROMPT},
                {"role": "user", "content": f"Project Brief:\n{format_brief(prompt)}"},
            ],
            response_format={"type": "json_object"},
        )
        parsed = json.loads(completion.choices[0].message.content)
        challenges = parsed.get("challenges", [])
        prompt.set_challenges(challenges)
        self.db.commit()
        return {"challenges": challenges}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


BRAINSTORM_PROMPT = """You are a startup ideation assistant. Given a project brief, generate:
- 3-5 concrete feature ideas that could extend the project
- 2-3 possible pivots if the current direction is too narrow
- 2-3 similar products in the market the builder should know about

Respond in JSON:
{
  "ideas": ["..."],
  "pivots": ["..."],
  "similar_products": ["..."]
}"""


@celery_app.task(bind=True, base=DatabaseTask, max_retries=3)
def generate_brainstorm(self, prompt_id: int):
    """Brainstorm ideas and pivots for the given prompt."""
    from db.models import Prompt

    try:
        prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        if not prompt:
            raise ValueError(f"Prompt {prompt_id} not found")

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": BRAINSTORM_PROMPT},
                {"role": "user", "content": f"Project Brief:\n{format_brief(prompt)}"},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(completion.choices[0].message.content)

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


SUMMARY_PROMPT = """You are a project memory assistant. Given a set of project briefs from the past week, produce a concise weekly digest.

Group by theme/tag, highlight decisions made, and note recurring blockers.
Respond in plain Markdown — no JSON."""


@celery_app.task(bind=True, base=DatabaseTask, max_retries=3)
def generate_weekly_summary(self, user_id: int, days: int = 7):
    """Generate a weekly digest for the given user."""
    from db.models import Prompt
    from db.models import Session as DbSession

    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        session_ids = [
            row[0]
            for row in self.db.query(DbSession.id).filter(
                (DbSession.owner_id == user_id) | (DbSession.collaborator_id == user_id)
            ).all()
        ]
        prompts = (
            self.db.query(Prompt)
            .filter(Prompt.session_id.in_(session_ids), Prompt.created_at >= cutoff)
            .order_by(Prompt.created_at.asc())
            .all()
        ) if session_ids else []
        if not prompts:
            return {"digest": "No briefs found in the last week.", "count": 0}

        briefs_block = "\n\n".join(format_brief(p) for p in prompts)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": briefs_block},
            ],
        )
        return {"digest": completion.choices[0].message.content, "count": len(prompts)}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


PROMPT_GEN_PROMPT = """You are a vibe-coding assistant. Your job is to generate a detailed, context-aware coding prompt that a developer can paste directly into an AI coding tool.

You will be given a project brief and the developer's answers to clarifying questions.

Generate a single, well-structured coding prompt in plain text. Be specific about stack, features, and constraints."""


@celery_app.task(bind=True, base=DatabaseTask, max_retries=3)
def generate_prompt_questions(self, prompt_id: int):
    """Generate 2-3 clarifying questions to ask before generating a coding prompt."""
    from db.models import Prompt

    try:
        prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        if not prompt:
            raise ValueError(f"Prompt {prompt_id} not found")

        system = """Given a project brief, generate 2-3 short clarifying questions that will help produce a better coding prompt. Focus on: tech stack preference, scope of the first implementation, and key edge cases to handle. Respond in JSON: {"questions": ["..."]}"""
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": format_brief(prompt)},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(completion.choices[0].message.content)

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(bind=True, base=DatabaseTask, max_retries=3)
def generate_coding_prompt(self, prompt_id: int, answers: str):
    """Generate a final vibe-coding prompt given the brief and user's answers."""
    from db.models import Prompt

    try:
        prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        if not prompt:
            raise ValueError(f"Prompt {prompt_id} not found")

        user_content = f"Project Brief:\n{format_brief(prompt)}\n\nDeveloper's answers:\n{answers}"
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": PROMPT_GEN_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        return {"coding_prompt": completion.choices[0].message.content}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
