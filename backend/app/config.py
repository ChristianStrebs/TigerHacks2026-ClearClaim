"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings.

    Values are read from the process environment and, when present, a local
    ``.env`` file. Secrets default to empty strings so the app can boot in a
    self-contained demo mode without any external credentials.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gemini
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_chat_model: str = Field(default="gemini-3.8-flash", alias="GEMINI_CHAT_MODEL")
    gemini_embed_model: str = Field(
        default="gemini-embedding-001", alias="GEMINI_EMBED_MODEL"
    )
    embed_dim: int = Field(default=768, alias="EMBED_DIM")
    gemini_timeout_seconds: float = Field(default=30, alias="GEMINI_TIMEOUT_SECONDS")
    gemini_fallback_models: str = Field(
        default="gemini-3.7-flash,gemini-3.5-flash-lite",
        alias="GEMINI_FALLBACK_MODELS",
    )

    # Supabase (pgvector)
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(
        default="", alias="SUPABASE_SERVICE_ROLE_KEY"
    )

    # CORS
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )

    # Demo benefits profile
    demo_deductible_total: float = Field(default=2000, alias="DEMO_DEDUCTIBLE_TOTAL")
    demo_deductible_met: float = Field(default=450, alias="DEMO_DEDUCTIBLE_MET")
    demo_coinsurance_rate: float = Field(default=0.2, alias="DEMO_COINSURANCE_RATE")
    demo_oop_max: float = Field(default=6000, alias="DEMO_OOP_MAX")

    @property
    def gemini_enabled(self) -> bool:
        """True when a real Gemini API key is configured."""
        return bool(self.gemini_api_key.strip())

    @property
    def supabase_enabled(self) -> bool:
        """True when Supabase credentials are configured."""
        return bool(self.supabase_url.strip() and self.supabase_service_role_key.strip())

    @property
    def gemini_generation_models(self) -> list[str]:
        """Primary chat model followed by backups tried when it is overloaded."""
        backups = [m.strip() for m in self.gemini_fallback_models.split(",") if m.strip()]
        return [self.gemini_chat_model, *[m for m in backups if m != self.gemini_chat_model]]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
