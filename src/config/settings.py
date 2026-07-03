from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(default="sqlite:///./data/agent.db")
    log_level: str = Field(default="INFO")

    # LLM provider — auto-detected from whichever key is set if left blank
    llm_provider: str = Field(default="")   # "anthropic" | "gemini"
    llm_model: str = Field(default="")      # uses provider default when blank
    llm_router_model: str = Field(default="")  # cheap/fast router model for classify_query (Phase 2+)

    # Provider keys — set exactly one
    anthropic_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")

    # Data-analyst agent limits
    max_upload_bytes: int = Field(default=104_857_600)
    data_dir: str = Field(default="./data")

    # Agent graph bounds (see spec/agent.md)
    max_iterations: int = Field(default=4)
    max_plan_steps: int = Field(default=5)
    max_total_steps: int = Field(default=8)

    # Sandboxed code execution
    sandbox_timeout_s: int = Field(default=20)
    result_row_cap: int = Field(default=200)
    result_cell_cap: int = Field(default=2000)

    # Artifact assembly (Phase 3a) — max points in a chart series (chart series
    # are always drawn from the already-capped ExecutionResult, then further
    # capped to this bound). Env: AGENT_CHART_MAX_POINTS.
    chart_max_points: int = Field(default=100)

    # Gemini cost-estimation price table (USD per 1K tokens; placeholders — verify
    # against current Gemini pricing before the Phase 3 cost UI ships)
    gemini_input_price_per_1k: float = Field(default=0.000075)
    gemini_output_price_per_1k: float = Field(default=0.0003)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
