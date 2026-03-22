from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.deps import verify_token, get_database
from shared.schemas import ChallengeRequest, ChallengeResponse
from worker.tasks import generate_challenges
from db.models import Prompt

router = APIRouter()


@router.post("/challenge", response_model=ChallengeResponse)
def create_challenge(
    request: ChallengeRequest,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database)
):
    """Generate probing questions for a prompt"""
    prompt = db.query(Prompt).filter(Prompt.id == request.prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # If challenges already exist in the database, return them immediately
    existing = prompt.get_challenges()
    if existing:
        return ChallengeResponse(challenges=existing)

    # If they don't exist, run the Gemini challenge generation task
    # We use .delay() to run it in the background, but here we wait for the result
    # because generating 3 questions with Gemini is usually very fast (< 2-3 seconds)
    task = generate_challenges.delay(request.prompt_id)
    try:
        result = task.get(timeout=30)
        return ChallengeResponse(challenges=result.get("challenges", []))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate challenges: {str(e)}")
