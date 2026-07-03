from config.settings import get_settings


def _make_provider():
    s = get_settings()
    provider = s.llm_provider

    # auto-detect from whichever key is set
    if not provider:
        if s.anthropic_api_key:
            provider = "anthropic"
        elif s.gemini_api_key:
            provider = "gemini"
        else:
            raise RuntimeError(
                "No LLM provider configured. Set AGENT_ANTHROPIC_API_KEY or "
                "AGENT_GEMINI_API_KEY in .env, or set AGENT_LLM_PROVIDER explicitly."
            )

    if provider == "anthropic":
        from llm.providers.anthropic import AnthropicProvider
        return AnthropicProvider(api_key=s.anthropic_api_key, model=s.llm_model)
    if provider == "gemini":
        from llm.providers.gemini import GeminiProvider
        return GeminiProvider(api_key=s.gemini_api_key, model=s.llm_model)

    raise RuntimeError(f"Unknown LLM provider: {provider!r}. Supported: anthropic, gemini")


class LLMClient:
    def __init__(self) -> None:
        self._provider = _make_provider()

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        return self._provider.call_model(prompt, system=system)

    def call_model_with_usage(self, prompt: str, *, system: str | None = None) -> tuple[str, dict]:
        """Like call_model, but also returns {"model", "prompt_tokens", "completion_tokens"}.

        Used by graph nodes that need to write a CostRecord per LLM call
        (see spec/agent.md -> Observability, spec/architecture.md -> Cost/Token
        Estimation Approach). Falls back to zeroed usage for providers that do
        not expose token counts (e.g. Anthropic in this skeleton).
        """
        if hasattr(self._provider, "call_model_with_usage"):
            return self._provider.call_model_with_usage(prompt, system=system)
        text = self._provider.call_model(prompt, system=system)
        model = getattr(self._provider, "_model", "") or getattr(self._provider, "model", "")
        return text, {"model": model, "prompt_tokens": 0, "completion_tokens": 0}
