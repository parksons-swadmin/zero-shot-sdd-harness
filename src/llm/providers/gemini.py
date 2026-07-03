from collections.abc import Iterator

from google import genai
from google.genai import types


class GeminiProvider:
    DEFAULT_MODEL = "gemini-3.1-pro"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    def call_model(self, prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        text, _usage = self.call_model_with_usage(prompt, system=system, model=model)
        return text

    def call_model_with_usage(
        self, prompt: str, *, system: str | None = None, model: str | None = None,
    ) -> tuple[str, dict]:
        # Per-call model override (e.g. classify_query routes to a cheaper model);
        # never mutates self._model so concurrent calls stay isolated.
        used_model = model or self._model
        config = types.GenerateContentConfig(
            system_instruction=system,
        ) if system else None
        response = self._client.models.generate_content(
            model=used_model,
            contents=prompt,
            config=config,
        )
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
        completion_tokens = getattr(usage, "candidates_token_count", None) if usage else None
        return response.text, {
            "model": used_model,
            "prompt_tokens": prompt_tokens or 0,
            "completion_tokens": completion_tokens or 0,
        }

    def call_model_streaming(
        self, prompt: str, *, system: str | None = None, model: str | None = None,
    ) -> Iterator[str]:
        """Real token streaming via generate_content_stream.

        Yields text chunks as they arrive; the generator's return value (the
        StopIteration.value) is the usage dict
        ``{"model", "prompt_tokens", "completion_tokens"}`` recovered from the
        final streamed response's usage_metadata, so token accounting is
        identical to the non-streaming call. Never mutates self._model.
        """
        used_model = model or self._model
        config = types.GenerateContentConfig(
            system_instruction=system,
        ) if system else None
        usage = {"model": used_model, "prompt_tokens": 0, "completion_tokens": 0}
        stream = self._client.models.generate_content_stream(
            model=used_model,
            contents=prompt,
            config=config,
        )
        for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                yield text
            meta = getattr(chunk, "usage_metadata", None)
            if meta is not None:
                prompt_tokens = getattr(meta, "prompt_token_count", None)
                completion_tokens = getattr(meta, "candidates_token_count", None)
                if prompt_tokens is not None:
                    usage["prompt_tokens"] = prompt_tokens
                if completion_tokens is not None:
                    usage["completion_tokens"] = completion_tokens
        return usage
