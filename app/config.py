import os
from dataclasses import dataclass
from math import isfinite

from dotenv import load_dotenv

from app.errors import LLMConfigurationError


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    api_key: str
    base_url: str | None
    timeout_seconds: float
    max_retries: int

    @classmethod
    def from_env(cls) -> "LLMSettings":
        load_dotenv()

        provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
        if provider != "openai":
            raise LLMConfigurationError(
                "Unsupported LLM_PROVIDER. Module 2 currently supports 'openai'."
            )

        api_key = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise LLMConfigurationError(
                "LLM_API_KEY (or OPENAI_API_KEY) must be configured."
            )

        try:
            timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
            max_retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        except ValueError as exc:
            raise LLMConfigurationError(
                "LLM_TIMEOUT_SECONDS and LLM_MAX_RETRIES must be numeric."
            ) from exc

        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise LLMConfigurationError("LLM_TIMEOUT_SECONDS must be greater than zero.")
        if max_retries < 0:
            raise LLMConfigurationError("LLM_MAX_RETRIES must not be negative.")

        base_url = os.getenv("LLM_BASE_URL", "").strip() or None
        return cls(
            provider=provider,
            model=os.getenv("LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
