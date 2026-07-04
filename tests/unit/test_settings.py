"""Settings — no provider/DB keys; AGENT_ prefix; sensible defaults."""


def test_defaults(monkeypatch):
    for var in (
        "AGENT_LOG_LEVEL",
        "AGENT_MAX_UPLOAD_MB",
        "AGENT_MAX_ROWS",
        "AGENT_HEADER_MATCH_THRESHOLD",
        "AGENT_RISK_TOP_N",
    ):
        monkeypatch.delenv(var, raising=False)
    import config.settings as m

    m._settings = None
    s = m.get_settings()
    assert s.log_level == "INFO"
    assert s.max_upload_mb == 25
    assert s.max_rows == 200000
    assert s.header_match_threshold == 85
    assert s.risk_top_n == 5


def test_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_HEADER_MATCH_THRESHOLD", "90")
    monkeypatch.setenv("AGENT_MAX_ROWS", "500")
    import config.settings as m

    m._settings = None
    s = m.get_settings()
    assert s.header_match_threshold == 90
    assert s.max_rows == 500


def test_no_provider_or_db_fields():
    from config.settings import Settings

    fields = set(Settings.model_fields)
    for forbidden in ("database_url", "anthropic_api_key", "gemini_api_key", "llm_provider", "llm_model"):
        assert forbidden not in fields, f"{forbidden} must not exist on the no-LLM/no-DB Settings"
