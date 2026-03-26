import os
import tempfile
import requests as http_requests

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.deps import verify_token, get_database
from shared.schemas import TranscribeRequest, TranscribeResponse, JobStatusResponse
from worker.tasks import process_audio
from worker.celery_app import celery_app
from db.models import Prompt, User, Session as DbSession

router = APIRouter()

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


@router.post("/transcribe", response_model=TranscribeResponse)
def create_transcription_job(
    request: TranscribeRequest,
    token: str = Depends(verify_token),
):
    """Download audio and queue transcription job."""
    response = http_requests.get(request.audio_url, timeout=30, stream=True)
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Could not download audio")

    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")

    os.makedirs("/tmp/recall/audio", exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg", dir="/tmp/recall/audio") as tmp:
        for chunk in response.iter_content(chunk_size=8192):
            tmp.write(chunk)
        audio_path = tmp.name

    task = process_audio.delay(
        audio_path,
        request.session_id,                          # telegram chat_id string
        request.telegram_username or "",
    )
    return TranscribeResponse(job_id=task.id)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Poll a Celery task for its result."""
    from celery.result import AsyncResult

    task = AsyncResult(job_id, app=celery_app)
    if task.state == "PENDING":
        return JobStatusResponse(job_id=job_id, status="pending")
    if task.state in ("STARTED", "PROGRESS"):
        return JobStatusResponse(job_id=job_id, status="processing")
    if task.state == "SUCCESS":
        result = task.result or {}
        if result.get("prompt_id"):
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
                    raw_summary=prompt.raw_summary,
                    tags=prompt.get_tags(),
                )
        return JobStatusResponse(job_id=job_id, status="completed")
    error_msg = str(task.result) if task.result else "Unknown error"
    return JobStatusResponse(job_id=job_id, status="failed", error=error_msg)


@router.get("/history")
def get_history(
    telegram_id: str,
    limit: int = 5,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Get recent prompts for a user, looked up by Telegram chat_id."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"prompts": []}

    # Show prompts from any shared session the user participates in
    session_ids = [
        row[0]
        for row in db.query(DbSession.id).filter(
            (DbSession.owner_id == user.id) | (DbSession.collaborator_id == user.id)
        ).all()
    ]
    if not session_ids:
        return {"prompts": []}
    prompts = (
        db.query(Prompt)
        .filter(Prompt.session_id.in_(session_ids))
        .order_by(Prompt.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"prompts": [p.to_dict() for p in prompts]}


@router.get("/prompts/{prompt_id}")
def get_prompt(
    prompt_id: int,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Get a specific prompt by ID."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt.to_dict()
