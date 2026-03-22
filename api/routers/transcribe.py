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
