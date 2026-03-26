from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    groq_api_key: str
    api_token: str
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "sqlite:///./recall.db"
    whisper_device: str = "cpu"
    # v2 additions
    huggingface_token: Optional[str] = None  # Required for pyannote diarization
    enable_diarization: bool = False          # Gate for speaker diarization feature
    embed_model: str = "nomic-ai/nomic-embed-text-v1"  # Local embedding model

    class Config:
        env_file = ".env"


settings = Settings()
