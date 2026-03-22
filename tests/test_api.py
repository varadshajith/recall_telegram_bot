import pytest
from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    """Confirm the 'Front Desk' is alive"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_transcribe_requires_auth(client: TestClient):
    """Check if unauthorized users are correctly blocked"""
    response = client.post(
        "/api/v1/transcribe", 
        json={"audio_url": "http://test", "session_id": "123"}
    )
    # 401 means "Who are you? Show me your ID!"
    assert response.status_code == 401


def test_transcribe_invalid_token(client: TestClient):
    """Check if a fake security token is correctly rejected"""
    response = client.post(
        "/api/v1/transcribe",
        json={"audio_url": "http://test", "session_id": "123"},
        headers={"Authorization": "Bearer invalid_token"}
    )
    assert response.status_code == 401
