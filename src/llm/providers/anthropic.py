from collections.abc import Iterator

import anthropic as _sdk


class AnthropicProvider:
    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = _sdk.Anthropic(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    def call_model(self, prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        kwargs: dict = dict(
            model=model or self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        msg = self._client.messages.create(**kwargs)
        return msg.content[0].text

    def call_model_streaming(
        self, prompt: str, *, system: str | None = None, model: str | None = None,
    ) -> Iterator[str]:
        """Interface-parity streaming for Anthropic: a single-chunk fallback so
        the shared LLMClient streaming interface does not diverge per-provider.
        Yields the full response as one chunk; returns a zeroed usage dict
        (Anthropic is not the streaming path in this skeleton)."""
        text = self.call_model(prompt, system=system, model=model)
        yield text
        return {"model": model or self._model, "prompt_tokens": 0, "completion_tokens": 0}
