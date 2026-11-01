import pytest

from citywheels.llm import ConfigError, make_client


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_MODEL", "GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_unknown_provider_is_a_config_error():
    with pytest.raises(ConfigError, match="'openai'"):
        make_client("openai")


def test_missing_key_names_the_variable():
    with pytest.raises(ConfigError, match="GROQ_API_KEY is not set"):
        make_client("groq")


def test_provider_from_env_with_default_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    client, model = make_client()

    assert str(client.base_url) == "https://api.groq.com/openai/v1/"
    assert model == "openai/gpt-oss-120b"


def test_gemini_is_the_default_provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    client, model = make_client()

    assert "generativelanguage.googleapis.com" in str(client.base_url)
    assert model == "gemini-3.5-flash-lite"


def test_ollama_needs_no_key():
    client, model = make_client("ollama")

    assert str(client.base_url) == "http://localhost:11434/v1/"
    assert model == "qwen3:4b"


def test_model_override_order(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "from-env")

    assert make_client("ollama")[1] == "from-env"
    assert make_client("ollama", model="from-arg")[1] == "from-arg"


def test_empty_model_variable_falls_back_to_default(monkeypatch):
    # .env.example ships with `LLM_MODEL=` left empty.
    monkeypatch.setenv("LLM_MODEL", "")

    assert make_client("ollama")[1] == "qwen3:4b"


def test_client_gives_up_on_a_dead_connection_after_two_minutes():
    client, _ = make_client("ollama")

    assert client.timeout == 120
