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
    cerebras_api_key: str = ""
    cerebras_model: str = "gpt-oss-120b,qwen-3.8-27b"
    mistral_api_key: str = ""
    mistral_model: str = "ministral-8b-latest,ministral-14b-latest"
    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3-super-120b-a12b:free,nvidia/nemotron-3-ultra-550b-a55b:free"
    sarvam_api_key: str = ""
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_speaker: str = ""
    sarvam_for_all: bool = False
    spread_load: bool = True
    answer_cache_s: int = 600
    cors_origins: str = "*"
    database_url: str = ""
    alert_poll_s: int = 120
    observation_poll_s: int = 900
    warm_poll_s: int = 1800
    smart_poll_s: int = 600
    role: str = "all"
    fcm_service_account: str = ""
    google_maps_api_key: str = ""
    phone_provider: str = "simulator"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    public_base_url: str = ""
    phone_poll_s: int = 600
    workers_enabled: bool = True
    wis2_enabled: bool = True
    wis2_broker: str = "globalbroker.meteo.fr"
    wis2_username: str = "everyone"
    wis2_password: str = "everyone"
    wis2_topic: str = "origin/a/wis2/#"
    alert_feed_url: str = "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
    http_timeout_s: float = 20.0

    model_order: str = "cerebras:0,groq:0,gemini:0,cerebras:1,groq:1,gemini:1,mistral:0,openrouter:0,mistral:1,openrouter:1,gemini:2"
    spread_providers: str = "cerebras,groq,gemini"
    tts_model: str = "gemini-3.8-flash-tts,gemini-3.8-flash-lite-tts,gemini-3.1-flash-tts-preview"
    azure_speech_key: str = ""
    azure_speech_region: str = "centralindia"
    stt_model: str = "whisper-large-v3-turbo"
    stt_engine: str = "auto"

    @property
    def tts_models(self) -> list[str]:
        return [m.strip() for m in self.tts_model.split(",") if m.strip()]

    @property
    def gemini_models(self) -> list[str]:
        return [m.strip() for m in self.gemini_model.split(",") if m.strip()] if self.gemini_api_key.strip() else []

    def models_for(self, provider: str) -> list[str]:
        key = getattr(self, f"{provider}_api_key", "").strip()
        models = getattr(self, f"{provider}_model", "")
        return [m.strip() for m in models.split(",") if m.strip()] if key else []

    @property
    def groq_models(self) -> list[str]:
        return self.models_for("groq")

    @property
    def llm_enabled(self) -> bool:
        return any(self.models_for(p) for p in ("gemini", "groq", "cerebras", "mistral", "openrouter"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
