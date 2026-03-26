from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

class TranscribeRequest(BaseModel):
    audio_url: str
    session_id: str          # Telegram chat_id (used as telegram_id for User lookup)
    telegram_username: Optional[str] = None


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
    tags: Optional[List[str]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Challenge
# ---------------------------------------------------------------------------

class ChallengeRequest(BaseModel):
    prompt_id: int


class ChallengeResponse(BaseModel):
    challenges: List[str]


# ---------------------------------------------------------------------------
# Prompt response (used by /history, /get)
# ---------------------------------------------------------------------------

class PromptResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    session_id: Optional[int] = None
    legacy_chat_id: Optional[str] = None
    features: List[str]
    decisions: List[str]
    next_steps: List[str]
    blockers: List[str]
    raw_summary: str
    tags: Optional[List[str]] = None
    speaker_attribution: Optional[List[dict]] = None
    created_at: datetime
    challenges: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Memory / search
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    telegram_id: str
    query: str
    limit: int = 3


class SearchResult(BaseModel):
    prompt_id: int
    score: float
    raw_summary: str
    tags: List[str]
    created_at: datetime


class SearchResponse(BaseModel):
    results: List[SearchResult]


class SummaryResponse(BaseModel):
    digest: str          # Markdown weekly digest
    period_days: int
    prompt_count: int


class EvolutionEntry(BaseModel):
    prompt_id: int
    created_at: datetime
    raw_summary: str
    tags: List[str]
    key_decisions: List[str]


class EvolutionResponse(BaseModel):
    entries: List[EvolutionEntry]


class TagBriefsResponse(BaseModel):
    tag: Optional[str]
    prompts: List[PromptResponse]


# ---------------------------------------------------------------------------
# Brainstorm / Prompt-gen
# ---------------------------------------------------------------------------

class BrainstormResponse(BaseModel):
    ideas: List[str]
    pivots: List[str]
    similar_products: List[str]


class PromptGenStartRequest(BaseModel):
    telegram_id: str


class PromptGenStartResponse(BaseModel):
    questions: List[str]
    prompt_id: int


class PromptGenCompleteRequest(BaseModel):
    prompt_id: int
    answers: str


class PromptGenCompleteResponse(BaseModel):
    coding_prompt: str


# ---------------------------------------------------------------------------
# Collaborators
# ---------------------------------------------------------------------------

class InviteRequest(BaseModel):
    inviter_telegram_id: str
    invitee_username: str   # Telegram @username without the @


class InviteResponse(BaseModel):
    invite_id: int
    status: str
    invitee_chat_id: Optional[str] = None  # Set if invitee already known


class RespondInviteRequest(BaseModel):
    invite_id: int
    responder_telegram_id: str
    accept: bool
