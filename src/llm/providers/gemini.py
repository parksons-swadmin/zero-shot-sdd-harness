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
