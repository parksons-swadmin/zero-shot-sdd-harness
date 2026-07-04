from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the fully-local AR aging tool.

    No provider or database keys exist — the tool is stateless, no-LLM, no-network.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENT_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    log_level: str = Field(default="INFO")
    max_upload_mb: int = Field(default=25)
    max_rows: int = Field(default=200000)
    header_match_threshold: int = Field(default=85)
    risk_top_n: int = Field(default=5)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
