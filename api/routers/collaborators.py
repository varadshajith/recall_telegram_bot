from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import verify_token, get_database
from db.models import User, Session as DbSession, CollaboratorInvite
from shared.schemas import InviteRequest, InviteResponse, RespondInviteRequest

router = APIRouter()


@router.post("/collaborators/invite", response_model=InviteResponse)
def send_invite(
    request: InviteRequest,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Create a collaborator invite for a session."""
    # Resolve inviter
    inviter = db.query(User).filter(User.telegram_id == request.inviter_telegram_id).first()
    if not inviter:
        raise HTTPException(status_code=404, detail="Inviter not found")

    # Find inviter's current session
    session = (
        db.query(DbSession)
        .filter(DbSession.owner_id == inviter.id)
        .order_by(DbSession.created_at.desc())
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="No session found for inviter")

    # Check for duplicate pending invite
    existing = db.query(CollaboratorInvite).filter(
        CollaboratorInvite.session_id == session.id,
        CollaboratorInvite.invitee_telegram_username == request.invitee_username,
        CollaboratorInvite.status == "pending",
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Invite already pending for this user")

    invite = CollaboratorInvite(
        session_id=session.id,
        inviter_id=inviter.id,
        invitee_telegram_username=request.invitee_username,
        status="pending",
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    # Check if invitee already has an account so bot can notify them
    invitee = db.query(User).filter(User.username == request.invitee_username).first()
    return InviteResponse(
        invite_id=invite.id,
        status="pending",
        invitee_chat_id=invitee.telegram_id if invitee else None,
    )


@router.post("/collaborators/respond")
def respond_to_invite(
    request: RespondInviteRequest,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Accept or decline a collaborator invite."""
    invite = db.query(CollaboratorInvite).filter(
        CollaboratorInvite.id == request.invite_id
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail=f"Invite already {invite.status}")

    responder = db.query(User).filter(
        User.telegram_id == request.responder_telegram_id
    ).first()
    if not responder:
        raise HTTPException(status_code=404, detail="Responder not found")

    if request.accept:
        invite.status = "accepted"
        # Add responder as collaborator on the session
        session = db.query(DbSession).filter(DbSession.id == invite.session_id).first()
        if session:
            session.collaborator_id = responder.id
        db.commit()
        return {"status": "accepted", "session_id": invite.session_id}
    else:
        invite.status = "declined"
        db.commit()
        return {"status": "declined"}


@router.get("/collaborators/pending")
def get_pending_invites(
    telegram_id: str,
    token: str = Depends(verify_token),
    db: Session = Depends(get_database),
):
    """Return pending invites for a user (looked up by username)."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user or not user.username:
        return {"invites": []}

    invites = db.query(CollaboratorInvite).filter(
        CollaboratorInvite.invitee_telegram_username == user.username,
        CollaboratorInvite.status == "pending",
    ).all()

    return {
        "invites": [
            {
                "invite_id": inv.id,
                "inviter_id": inv.inviter_id,
                "session_id": inv.session_id,
            }
            for inv in invites
        ]
    }
