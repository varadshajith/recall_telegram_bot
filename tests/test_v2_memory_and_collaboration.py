import json
from datetime import datetime, timedelta

import worker.tasks as tasks
from db.models import User, Session as DbSession, Prompt


def auth_headers(api_token: str) -> dict:
    return {"Authorization": f"Bearer {api_token}"}


def seed_users_and_sessions(db_session):
    owner = User(telegram_id="111", username="owner")
    collaborator = User(telegram_id="222", username="collab")
    db_session.add_all([owner, collaborator])
    db_session.commit()
    db_session.refresh(owner)
    db_session.refresh(collaborator)

    shared = DbSession(owner_id=owner.id, collaborator_id=collaborator.id)
    owner_solo = DbSession(owner_id=owner.id, collaborator_id=None)
    collaborator_solo = DbSession(owner_id=collaborator.id, collaborator_id=None)

    db_session.add_all([shared, owner_solo, collaborator_solo])
    db_session.commit()
    db_session.refresh(shared)
    db_session.refresh(owner_solo)
    db_session.refresh(collaborator_solo)

    return owner, collaborator, shared, owner_solo, collaborator_solo


def seed_prompt(
    db_session,
    *,
    user_id: int,
    session_id: int,
    created_at: datetime,
    raw_summary: str,
    tags: list[str],
    embedding: list[float] | None = None,
) -> Prompt:
    prompt = Prompt(
        user_id=user_id,
        session_id=session_id,
        legacy_chat_id="legacy",
        transcript="transcript",
        raw_summary=raw_summary,
        created_at=created_at,
    )
    prompt.set_tags(tags)
    prompt.set_features([])
    prompt.set_decisions([])
    prompt.set_next_steps([])
    prompt.set_blockers([])
    if embedding is not None:
        prompt.set_embedding(embedding)
    db_session.add(prompt)
    db_session.commit()
    db_session.refresh(prompt)
    return prompt


def test_history_includes_shared_session_prompts(db_session, client, api_token):
    owner, collaborator, shared, owner_solo, _ = seed_users_and_sessions(db_session)

    p_shared = seed_prompt(
        db_session,
        user_id=owner.id,
        session_id=shared.id,
        created_at=datetime.utcnow() - timedelta(days=1),
        raw_summary="shared",
        tags=["api"],
        embedding=[0.1],
    )
    _ = seed_prompt(
        db_session,
        user_id=owner.id,
        session_id=owner_solo.id,  # collaborator should NOT see this
        created_at=datetime.utcnow() - timedelta(days=2),
        raw_summary="solo",
        tags=["secret"],
        embedding=[0.9],
    )

    resp = client.get(
        "/api/v1/history",
        headers=auth_headers(api_token),
        params={"telegram_id": collaborator.telegram_id, "limit": 5},
    )
    assert resp.status_code == 200
    prompts = resp.json()["prompts"]
    ids = {p["id"] for p in prompts}
    assert p_shared.id in ids


def test_search_only_returns_prompts_from_user_sessions(db_session, client, api_token, monkeypatch):
    owner, collaborator, shared, owner_solo, _ = seed_users_and_sessions(db_session)

    # Seed embeddings so the mocked cosine similarity can rank deterministically.
    p1 = seed_prompt(
        db_session,
        user_id=owner.id,
        session_id=shared.id,
        created_at=datetime.utcnow() - timedelta(days=1),
        raw_summary="shared-high",
        tags=["tagA"],
        embedding=[0.8],
    )
    _ = seed_prompt(
        db_session,
        user_id=collaborator.id,
        session_id=shared.id,
        created_at=datetime.utcnow() - timedelta(days=1, hours=1),
        raw_summary="shared-low",
        tags=["tagB"],
        embedding=[0.2],
    )
    _ = seed_prompt(
        db_session,
        user_id=owner.id,
        session_id=owner_solo.id,  # excluded for collaborator
        created_at=datetime.utcnow() - timedelta(days=1, hours=2),
        raw_summary="solo-high",
        tags=["tagC"],
        embedding=[0.95],
    )

    # Deterministic embedding / similarity for tests.
    monkeypatch.setattr(tasks, "embed_text", lambda _: [0.0])
    monkeypatch.setattr(tasks, "cosine_similarity", lambda _a, b: float(b[0]) if b else 0.0)

    resp = client.post(
        "/api/v1/search",
        headers=auth_headers(api_token),
        json={"telegram_id": collaborator.telegram_id, "query": "anything", "limit": 3},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    returned_ids = {r["prompt_id"] for r in results}
    assert p1.id in returned_ids
    # Should exclude prompt from owner_solo session.
    assert all(r["raw_summary"] != "solo-high" for r in results)
    # Should rank by embedding[0] (descending).
    assert results[0]["prompt_id"] == p1.id


def test_brainstorm_uses_latest_prompt_across_user_sessions(db_session, client, api_token, monkeypatch):
    owner, collaborator, shared, _owner_solo, collaborator_solo = seed_users_and_sessions(db_session)

    # Older prompt in collaborator's solo session
    seed_prompt(
        db_session,
        user_id=collaborator.id,
        session_id=collaborator_solo.id,
        created_at=datetime.utcnow() - timedelta(days=5),
        raw_summary="collab-solo-old",
        tags=["x"],
        embedding=[0.1],
    )

    # Newest prompt in the shared session (expected to be selected)
    p_latest = seed_prompt(
        db_session,
        user_id=owner.id,
        session_id=shared.id,
        created_at=datetime.utcnow() - timedelta(hours=1),
        raw_summary="shared-latest",
        tags=["y"],
        embedding=[0.1],
    )

    class DummyAsyncResult:
        def __init__(self, payload):
            self._payload = payload

        def get(self, timeout=None):
            return self._payload

    class DummyCeleryTask:
        def __init__(self):
            self.last_prompt_id = None

        def delay(self, prompt_id):
            self.last_prompt_id = prompt_id
            return DummyAsyncResult(
                {"ideas": ["i1"], "pivots": ["p1"], "similar_products": ["s1"]}
            )

    dummy = DummyCeleryTask()
    monkeypatch.setattr(tasks, "generate_brainstorm", dummy)

    resp = client.post(
        "/api/v1/brainstorm",
        headers=auth_headers(api_token),
        params={"telegram_id": collaborator.telegram_id},
    )
    assert resp.status_code == 200
    assert resp.json()["ideas"] == ["i1"]
    assert dummy.last_prompt_id == p_latest.id


def test_collaborator_invite_and_accept_updates_session(db_session, client, api_token):
    inviter = User(telegram_id="111", username="inviter")
    invitee = User(telegram_id="333", username="inviteeUser")
    db_session.add_all([inviter, invitee])
    db_session.commit()
    db_session.refresh(inviter)
    db_session.refresh(invitee)

    # Inviter's current session (owner)
    session = DbSession(owner_id=inviter.id, collaborator_id=None)
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    headers = auth_headers(api_token)

    invite_resp = client.post(
        "/api/v1/collaborators/invite",
        headers=headers,
        json={"inviter_telegram_id": inviter.telegram_id, "invitee_username": "inviteeUser"},
    )
    assert invite_resp.status_code == 200
    invite_data = invite_resp.json()
    invite_id = invite_data["invite_id"]
    assert invite_data["invitee_chat_id"] == invitee.telegram_id

    respond_resp = client.post(
        "/api/v1/collaborators/respond",
        headers=headers,
        json={
            "invite_id": invite_id,
            "responder_telegram_id": invitee.telegram_id,
            "accept": True,
        },
    )
    assert respond_resp.status_code == 200
    assert respond_resp.json()["status"] == "accepted"

    # Verify DB update
    updated = db_session.query(DbSession).filter(DbSession.id == session.id).first()
    assert updated.collaborator_id == invitee.id

