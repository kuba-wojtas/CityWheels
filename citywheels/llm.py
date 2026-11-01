import os
from dataclasses import dataclass

from openai import OpenAI


@dataclass(frozen=True)
class Provider:
    base_url: str
    key_env: str | None
    default_model: str


# All three speak the OpenAI chat completions format, so one client covers them.
# gemini-3.5-flash-lite over 3.8-flash: the free tier of 3.8 allows only 20 requests a day.
PROVIDERS = {
    "gemini": Provider(
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "GEMINI_API_KEY",
        "gemini-3.5-flash-lite",
    ),
    "groq": Provider("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b"),
    "ollama": Provider("http://localhost:11434/v1", None, "qwen3:4b"),
}


class ConfigError(Exception):
    pass


def resolve_provider(provider: str | None = None) -> str:
    name = provider or os.getenv("LLM_PROVIDER") or "gemini"
    if name not in PROVIDERS:
        raise ConfigError(f"Unknown provider {name!r}, expected one of: {', '.join(PROVIDERS)}")
    return name


def make_client(provider: str | None = None, model: str | None = None) -> tuple[OpenAI, str]:
    config = PROVIDERS[resolve_provider(provider)]

    # Ollama ignores the key, but the OpenAI client refuses to start without one.
    api_key = "ollama"
    if config.key_env:
        api_key = os.getenv(config.key_env)
        if not api_key:
            raise ConfigError(f"{config.key_env} is not set, see .env.example")

    # The default timeout is 10 minutes, a dead connection (e.g. after the laptop slept)
    # froze an eval run. 120 s still leaves room for Ollama loading the model.
    client = OpenAI(base_url=config.base_url, api_key=api_key, timeout=120)
    return client, model or os.getenv("LLM_MODEL") or config.default_model
