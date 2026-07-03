from collections.abc import Callable

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

    def call_model(self, prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        return self._provider.call_model(prompt, system=system, model=model)

    def call_model_with_usage(
        self, prompt: str, *, system: str | None = None, model: str | None = None,
    ) -> tuple[str, dict]:
        """Like call_model, but also returns {"model", "prompt_tokens", "completion_tokens"}.

        Used by graph nodes that need to write a CostRecord per LLM call
        (see spec/agent.md -> Observability, spec/architecture.md -> Cost/Token
        Estimation Approach). Falls back to zeroed usage for providers that do
        not expose token counts (e.g. Anthropic in this skeleton).

        `model`, when provided, overrides the provider's configured model for
        THIS call only (e.g. classify_query routing to a cheaper router model).
        """
        if hasattr(self._provider, "call_model_with_usage"):
            return self._provider.call_model_with_usage(prompt, system=system, model=model)
        text = self._provider.call_model(prompt, system=system, model=model)
        used_model = model or getattr(self._provider, "_model", "") or getattr(self._provider, "model", "")
        return text, {"model": used_model, "prompt_tokens": 0, "completion_tokens": 0}

    def call_model_streaming(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> tuple[str, dict]:
        """Stream a response token-by-token (Phase 3c).

        Delegates to the provider's `call_model_streaming` generator, invoking
        `on_chunk(text)` for each streamed chunk while accumulating the full
        text, and returns `(full_text, usage)` where `usage` is
        `{"model", "prompt_tokens", "completion_tokens"}` recovered from the
        provider (identical accounting to `call_model_with_usage`). Falls back
        to a single non-streaming call for providers without native streaming.
        """
        if hasattr(self._provider, "call_model_streaming"):
            gen = self._provider.call_model_streaming(prompt, system=system, model=model)
            parts: list[str] = []
            usage: dict = {}
            while True:
                try:
                    chunk = next(gen)
                except StopIteration as stop:
                    usage = stop.value or {}
                    break
                parts.append(chunk)
                if on_chunk is not None and chunk:
                    on_chunk(chunk)
            text = "".join(parts)
            used_model = usage.get("model") or model or getattr(self._provider, "_model", "")
            return text, {
                "model": used_model,
                "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
                "completion_tokens": usage.get("completion_tokens", 0) or 0,
            }

        # Provider without native streaming: one call, one chunk.
        text, usage = self.call_model_with_usage(prompt, system=system, model=model)
        if on_chunk is not None and text:
            on_chunk(text)
        return text, usage
