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
