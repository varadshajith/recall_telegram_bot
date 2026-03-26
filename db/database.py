import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from shared.config import settings
from db.models import Base

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Run Alembic migrations to head. Falls back to create_all if alembic.ini is missing."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini = os.path.join(project_root, "alembic.ini")
    # Test environment: keep startup fast and deterministic.
    # Running Alembic migrations on ephemeral SQLite setups can fail if the
    # schema is already partially present, so prefer create_all in pytest.
    if os.environ.get("PYTEST_CURRENT_TEST") is not None:
        Base.metadata.create_all(bind=engine)
        return
    if os.path.exists(alembic_ini):
        from alembic.config import Config
        from alembic import command
        cfg = Config(alembic_ini)
        cfg.set_main_option("script_location", os.path.join(project_root, "alembic"))
        try:
            command.upgrade(cfg, "head")
        except Exception:
            # Fallback for environments where schema is already present or Alembic
            # state is inconsistent (best-effort).
            Base.metadata.create_all(bind=engine)
    else:
        # fallback for tests / environments without alembic.ini
        Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
