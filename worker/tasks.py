import os
import sys
import tempfile
from celery import Task

# Add project root to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.celery_app import celery_app
from shared.config import settings
from groq import Groq
from pydub import AudioSegment

# Initialize Groq client
client = Groq(api_key=settings.groq_api_key)


class DatabaseTask(Task):
    """Task that has access to database"""
    _db = None

    @property
    def db(self):
        if self._db is None:
            from db.database import SessionLocal
            self._db = SessionLocal()
        return self._db


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


def clean_list(items):
    """Filter out common LLM placeholder strings like 'n', 'none', 'n/a'"""
    if not items or not isinstance(items, list):
        return []
    result = []
    for item in items:
        if item and str(item).lower().strip() not in ('n', 'none', 'n/a'):
            result.append(item)
    return result


@celery_app.task(bind=True, base=DatabaseTask, max_retries=3)
def process_audio(self, audio_path: str, session_id: str):
    """Transcribe audio (with chunking if > 10m) and generate dev brief using Groq"""
    from db.models import Prompt
    import json

    try:
        # Step 1: Handle Audio Chunking and Transcription
        audio = AudioSegment.from_file(audio_path)
        duration_ms = len(audio)
        ten_minutes_ms = 10 * 60 * 1000
        
        full_transcript = []
        
        if duration_ms > ten_minutes_ms:
            # Split into 10-minute chunks
            for i in range(0, duration_ms, ten_minutes_ms):
                chunk = audio[i:i + ten_minutes_ms]
                with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
                    chunk.export(tmp.name, format="ogg")
                    with open(tmp.name, "rb") as audio_file:
                        # Transcribe chunk with Groq Whisper
                        transcription = client.audio.transcriptions.create(
                            file=(tmp.name, audio_file.read()),
                            model="whisper-large-v3",
                        )
                        full_transcript.append(transcription.text)
                    os.remove(tmp.name)
        else:
            # Single chunk transcription
            with open(audio_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=(audio_path, audio_file.read()),
                    model="whisper-large-v3",
                )
                full_transcript.append(transcription.text)

        transcript_text = " ".join(full_transcript)

        # Clean up audio file after transcription
        if os.path.exists(audio_path):
            os.remove(audio_path)

        # Step 2: Call Groq Llama for summarization
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript:\n{transcript_text}"}
            ],
            response_format={"type": "json_object"}
        )

        parsed = json.loads(completion.choices[0].message.content)

        # Step 3: Save to database
        prompt = Prompt(session_id=session_id)
        prompt.set_features(clean_list(parsed.get("features", [])))
        prompt.set_decisions(clean_list(parsed.get("decisions", [])))
        prompt.set_next_steps(clean_list(parsed.get("next_steps", [])))
        prompt.set_blockers(clean_list(parsed.get("blockers", [])))
        prompt.raw_summary = f"Building: {parsed.get('building', '')}\n\nContext: {parsed.get('context', '')}"

        self.db.add(prompt)
        self.db.commit()
        self.db.refresh(prompt)

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
    """Generate probing questions for a prompt using Llama"""
    from db.models import Prompt
    import json

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

        # Call Groq Llama
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": CHALLENGE_PROMPT},
                {"role": "user", "content": f"Project Brief:\n{brief}"}
            ],
            response_format={"type": "json_object"}
        )

        parsed = json.loads(completion.choices[0].message.content)
        challenges = parsed.get("challenges", [])

        # Update prompt
        prompt.set_challenges(challenges)
        self.db.commit()

        return {"challenges": challenges}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
