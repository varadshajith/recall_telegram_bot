from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import verify_token, get_database
from db.models import Prompt, User, Session as DbSession
from shared.schemas import (
    SearchRequest, SearchResponse, SearchResult,
    SummaryResponse,
    EvolutionEntry, EvolutionResponse,
    TagBriefsResponse, PromptResponse,
    BrainstormResponse,
    PromptGenStartRequest, PromptGenStartResponse,
    PromptGenCompleteRequest, PromptGenCompleteResponse,
)

router = APIRouter()


def _get_user_or_404(telegram_id: str, db: Session):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Send a voice message first.")
    return user


def _session_ids_for_user(user_id: int, db: Session) -> list[int]:
    """Sessions the user participates in (owner or collaborator)."""
    rows = db.query(DbSession.id).filter(
        (DbSession.owner_id == user_id) | (DbSession.collaborator_id == user_id)
    ).all()
    return [r[0] for r in rows]


def _latest_prompt_or_404(user_id: int, db: Session):
    session_ids = _session_ids_for_user(user_id, db)
    if not session_ids:
        raise HTTPException(status_code=404, detail="No briefs found. Send a voice message first.")
    prompt = (
        db.query(Prompt)
        .filter(Prompt.session_id.in_(session_ids))
        .order_by(Prompt.created_at.desc())
        .first()
    )
    if not prompt:
        raise HTTPException(status_code=404, detail="No briefs found. Send a voice message first.")
    return prompt


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------

@router.post("/search", response_model=SearchResponse)
def semantic_search(
    request: SearchRequest,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Embed the query and rank all user briefs by cosine similarity."""
    from worker.tasks import embed_text, cosine_similarity

    user = _get_user_or_404(request.telegram_id, db)
    session_ids = _session_ids_for_user(user.id, db)
    if not session_ids:
        return SearchResponse(results=[])

    prompts = db.query(Prompt).filter(
        Prompt.session_id.in_(session_ids),
        Prompt.embedding.isnot(None),
    ).all()

    if not prompts:
        return SearchResponse(results=[])

    query_vec = embed_text(f"search_query: {request.query}")
    scored = []
    for p in prompts:
        doc_vec = p.get_embedding()
        if doc_vec:
            score = cosine_similarity(query_vec, doc_vec)
            scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [
        SearchResult(
            prompt_id=p.id,
            score=round(score, 4),
            raw_summary=p.raw_summary or "",
            tags=p.get_tags(),
            created_at=p.created_at,
        )
        for score, p in scored[: request.limit]
    ]
    return SearchResponse(results=results)


# ---------------------------------------------------------------------------
# GET /summary
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=SummaryResponse)
def weekly_summary(
    telegram_id: str,
    days: int = 7,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Generate a weekly digest via Celery task (waited synchronously)."""
    from worker.tasks import generate_weekly_summary

    user = _get_user_or_404(telegram_id, db)
    task = generate_weekly_summary.delay(user.id, days)
    try:
        result = task.get(timeout=60)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {e}")
    return SummaryResponse(
        digest=result["digest"],
        period_days=days,
        prompt_count=result["count"],
    )


# ---------------------------------------------------------------------------
# GET /evolution
# ---------------------------------------------------------------------------

@router.get("/evolution", response_model=EvolutionResponse)
def idea_evolution(
    telegram_id: str,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Return all briefs for this user in chronological order as a timeline."""
    user = _get_user_or_404(telegram_id, db)
    session_ids = _session_ids_for_user(user.id, db)
    prompts = (
        db.query(Prompt)
        .filter(Prompt.session_id.in_(session_ids))
        .order_by(Prompt.created_at.asc())
        .all()
    )
    if not prompts:
        return EvolutionResponse(entries=[])
    entries = [
        EvolutionEntry(
            prompt_id=p.id,
            created_at=p.created_at,
            raw_summary=p.raw_summary or "",
            tags=p.get_tags(),
            key_decisions=p.get_decisions()[:3],  # top 3 decisions per entry
        )
        for p in prompts
    ]
    return EvolutionResponse(entries=entries)


# ---------------------------------------------------------------------------
# GET /ideas
# ---------------------------------------------------------------------------

@router.get("/ideas", response_model=TagBriefsResponse)
def filter_by_tag(
    telegram_id: str,
    tag: Optional[str] = None,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Return briefs filtered by auto-generated tag. If no tag given, returns all."""
    user = _get_user_or_404(telegram_id, db)
    session_ids = _session_ids_for_user(user.id, db)
    prompts = (
        db.query(Prompt)
        .filter(Prompt.session_id.in_(session_ids))
        .order_by(Prompt.created_at.desc())
        .all()
    )
    if not session_ids:
        return TagBriefsResponse(tag=tag, prompts=[])
    if tag:
        prompts = [p for p in prompts if tag.lower() in [t.lower() for t in p.get_tags()]]

    return TagBriefsResponse(
        tag=tag,
        prompts=[PromptResponse(**p.to_dict()) for p in prompts],
    )


# ---------------------------------------------------------------------------
# POST /brainstorm
# ---------------------------------------------------------------------------

@router.post("/brainstorm", response_model=BrainstormResponse)
def brainstorm(
    telegram_id: str,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Brainstorm ideas and pivots for the user's latest brief."""
    from worker.tasks import generate_brainstorm

    user = _get_user_or_404(telegram_id, db)
    prompt = _latest_prompt_or_404(user.id, db)

    task = generate_brainstorm.delay(prompt.id)
    try:
        result = task.get(timeout=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Brainstorm failed: {e}")
    return BrainstormResponse(
        ideas=result.get("ideas", []),
        pivots=result.get("pivots", []),
        similar_products=result.get("similar_products", []),
    )


# ---------------------------------------------------------------------------
# POST /prompt/start  and  POST /prompt/complete
# ---------------------------------------------------------------------------

@router.post("/prompt/start", response_model=PromptGenStartResponse)
def prompt_gen_start(
    request: PromptGenStartRequest,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Generate clarifying questions for the user's latest brief."""
    from worker.tasks import generate_prompt_questions

    user = _get_user_or_404(request.telegram_id, db)
    prompt = _latest_prompt_or_404(user.id, db)

    task = generate_prompt_questions.delay(prompt.id)
    try:
        result = task.get(timeout=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Question generation failed: {e}")
    return PromptGenStartResponse(
        questions=result.get("questions", []),
        prompt_id=prompt.id,
    )


@router.post("/prompt/complete", response_model=PromptGenCompleteResponse)
def prompt_gen_complete(
    request: PromptGenCompleteRequest,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Generate the final vibe-coding prompt given the user's answers."""
    from worker.tasks import generate_coding_prompt

    prompt = db.query(Prompt).filter(Prompt.id == request.prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    task = generate_coding_prompt.delay(request.prompt_id, request.answers)
    try:
        result = task.get(timeout=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prompt generation failed: {e}")
    return PromptGenCompleteResponse(coding_prompt=result.get("coding_prompt", ""))
