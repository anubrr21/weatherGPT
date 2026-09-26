from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        extra="ignore",
    )

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    cors_origins: str = "*"
    alert_feed_url: str = "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
    http_timeout_s: float = 20.0

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key.strip() or self.groq_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
