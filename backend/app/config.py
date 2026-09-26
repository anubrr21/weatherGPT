from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        extra="ignore",
    )

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite,gemini-3.7-flash,gemini-3.8-flash"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b,openai/gpt-oss-20b"
    cors_origins: str = "*"
    alert_feed_url: str = "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
    http_timeout_s: float = 20.0

    model_order: str = "gemini:0,groq:0,gemini:1,groq:1,gemini:2"
    tts_model: str = "gemini-3.8-flash-tts,gemini-3.8-flash-lite-tts"
    stt_model: str = "whisper-large-v3-turbo"

    @property
    def tts_models(self) -> list[str]:
        return [m.strip() for m in self.tts_model.split(",") if m.strip()]

    @property
    def gemini_models(self) -> list[str]:
        return [m.strip() for m in self.gemini_model.split(",") if m.strip()] if self.gemini_api_key.strip() else []

    @property
    def groq_models(self) -> list[str]:
        return [m.strip() for m in self.groq_model.split(",") if m.strip()] if self.groq_api_key.strip() else []

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key.strip() or self.groq_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
