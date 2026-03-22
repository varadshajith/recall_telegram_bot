from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    groq_api_key: str
    api_token: str
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "sqlite:///./recall.db"
    whisper_device: str = "cpu"

    class Config:
        env_file = ".env"


settings = Settings()
