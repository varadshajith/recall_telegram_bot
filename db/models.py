import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(255), index=True, nullable=False)
    features = Column(Text, default="[]")  # JSON list
    decisions = Column(Text, default="[]")
    next_steps = Column(Text, default="[]")
    blockers = Column(Text, default="[]")
    raw_summary = Column(Text, default="")
    challenges = Column(Text, nullable=True)  # JSON list
    created_at = Column(DateTime, default=datetime.utcnow)

    def get_features(self) -> list:
        return json.loads(self.features)

    def set_features(self, features: list):
        self.features = json.dumps(features)

    def get_decisions(self) -> list:
        return json.loads(self.decisions)

    def set_decisions(self, decisions: list):
        self.decisions = json.dumps(decisions)

    def get_next_steps(self) -> list:
        return json.loads(self.next_steps)

    def set_next_steps(self, next_steps: list):
        self.next_steps = json.dumps(next_steps)

    def get_blockers(self) -> list:
        return json.loads(self.blockers)

    def set_blockers(self, blockers: list):
        self.blockers = json.dumps(blockers)

    def get_challenges(self) -> list:
        return json.loads(self.challenges) if self.challenges else []

    def set_challenges(self, challenges: list):
        self.challenges = json.dumps(challenges) if challenges else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "features": self.get_features(),
            "decisions": self.get_decisions(),
            "next_steps": self.get_next_steps(),
            "blockers": self.get_blockers(),
            "raw_summary": self.raw_summary,
            "challenges": self.get_challenges(),
            "created_at": self.created_at.isoformat(),
        }
