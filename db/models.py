import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("Session", back_populates="owner", foreign_keys="Session.owner_id")
    prompts = relationship("Prompt", back_populates="user")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    collaborator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="sessions", foreign_keys=[owner_id])
    collaborator = relationship("User", foreign_keys=[collaborator_id])
    prompts = relationship("Prompt", back_populates="session")
    invites = relationship("CollaboratorInvite", back_populates="session")


class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True)
    # v2 identity FK columns (nullable for backward compat with v1 data)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    # v1 compat: original string chat_id kept as legacy reference
    legacy_chat_id = Column(String(255), nullable=True, index=True)
    # content
    transcript = Column(Text, default="")
    features = Column(Text, default="[]")  # JSON list
    decisions = Column(Text, default="[]")
    next_steps = Column(Text, default="[]")
    blockers = Column(Text, default="[]")
    raw_summary = Column(Text, default="")
    challenges = Column(Text, nullable=True)  # JSON list
    tags = Column(Text, default="[]")  # JSON list — auto-generated domain tags
    speaker_attribution = Column(Text, nullable=True)  # JSON: [{speaker, text}, ...]
    embedding = Column(Text, nullable=True)  # JSON float list — Nomic Embed vector
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="prompts")
    session = relationship("Session", back_populates="prompts")

    # --- JSON accessors ---
    def get_features(self) -> list:
        return json.loads(self.features or "[]")

    def set_features(self, features: list):
        self.features = json.dumps(features)

    def get_decisions(self) -> list:
        return json.loads(self.decisions or "[]")

    def set_decisions(self, decisions: list):
        self.decisions = json.dumps(decisions)

    def get_next_steps(self) -> list:
        return json.loads(self.next_steps or "[]")

    def set_next_steps(self, next_steps: list):
        self.next_steps = json.dumps(next_steps)

    def get_blockers(self) -> list:
        return json.loads(self.blockers or "[]")

    def set_blockers(self, blockers: list):
        self.blockers = json.dumps(blockers)

    def get_challenges(self) -> list:
        return json.loads(self.challenges) if self.challenges else []

    def set_challenges(self, challenges: list):
        self.challenges = json.dumps(challenges) if challenges else None

    def get_tags(self) -> list:
        return json.loads(self.tags or "[]")

    def set_tags(self, tags: list):
        self.tags = json.dumps(tags)

    def get_embedding(self) -> list:
        return json.loads(self.embedding) if self.embedding else []

    def set_embedding(self, vec: list):
        self.embedding = json.dumps(vec)

    def get_speaker_attribution(self) -> list:
        if not self.speaker_attribution:
            return []
        try:
            return json.loads(self.speaker_attribution)
        except Exception:
            return []

    def set_speaker_attribution(self, attribution: list):
        # Store an empty list as NULL to keep DB compact.
        self.speaker_attribution = json.dumps(attribution) if attribution else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "legacy_chat_id": self.legacy_chat_id,
            "transcript": self.transcript or "",
            "features": self.get_features(),
            "decisions": self.get_decisions(),
            "next_steps": self.get_next_steps(),
            "blockers": self.get_blockers(),
            "raw_summary": self.raw_summary or "",
            "challenges": self.get_challenges(),
            "tags": self.get_tags(),
            "speaker_attribution": self.get_speaker_attribution(),
            "created_at": self.created_at.isoformat(),
        }


class CollaboratorInvite(Base):
    __tablename__ = "collaborator_invites"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    inviter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    invitee_telegram_username = Column(String(255), nullable=False)
    status = Column(String(20), default="pending")  # pending / accepted / declined
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="invites")
    inviter = relationship("User")
