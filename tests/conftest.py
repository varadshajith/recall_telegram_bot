import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base
from api.main import app
from api.deps import get_database as api_get_database
from shared.config import settings

# We use an in-memory database for testing so it's super fast and doesn't mess with your real records
TEST_DATABASE_URL = "sqlite:///:memory:"

# SQLite in-memory DBs are per-connection; StaticPool ensures all sessions
# share the same underlying connection so schema created by create_all()
# is visible during requests.
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database for each test and clean it up afterward"""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    """Provides a virtual client to talk to our API without starting the whole server.

    Also overrides DB dependency so endpoints operate on the in-memory test DB.
    """
    app.dependency_overrides[api_get_database] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides = {}


@pytest.fixture
def api_token():
    """Easy access to our security token for testing"""
    return settings.api_token
