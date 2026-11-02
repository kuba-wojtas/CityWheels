# openai 3.x builds its errors on httpx2 (not httpx), so the fake errors need it too.
import httpx2
import pytest
from fakes import FakeClient, completion, tool_call
from openai import APIConnectionError, APITimeoutError, RateLimitError

from citywheels import cli
from citywheels.llm import ConfigError

REQUEST = httpx2.Request("POST", "http://fake/v1/chat/completions")


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: None)


def use_client(monkeypatch, client: FakeClient):
    monkeypatch.setattr(cli, "make_client", lambda provider, model: (client, "fake"))


def type_in(monkeypatch, *lines: str):
    remaining = list(lines)

    def fake_input(prompt=""):
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)


def refund_turn(booking_id: str, answer: str) -> list:
    return [
        completion(tool_calls=[tool_call("c1", "calculate_refund", {"booking_id": booking_id})]),
        completion(content=answer),
    ]


def test_single_question_shows_tool_calls_and_answer(monkeypatch, capsys):
    use_client(monkeypatch, FakeClient(*refund_turn("CW-1002", "You get 340 EUR back.")))

    code = cli.main(["How much for CW-1002?"])

    out = capsys.readouterr().out
    assert code == 0
    assert '[tool] calculate_refund {"booking_id": "CW-1002"} -> ok' in out
    assert out.strip().endswith("You get 340 EUR back.")


def test_quiet_hides_tool_calls(monkeypatch, capsys):
    use_client(monkeypatch, FakeClient(*refund_turn("CW-1002", "You get 340 EUR back.")))

    cli.main(["-q", "How much for CW-1002?"])

    assert capsys.readouterr().out == "You get 340 EUR back.\n"


def test_config_error_is_a_message_not_a_traceback(monkeypatch, capsys):
    def broken(provider, model):
        raise ConfigError("GEMINI_API_KEY is not set, see .env.example")

    monkeypatch.setattr(cli, "make_client", broken)

    code = cli.main(["Hi"])

    assert code == 2
    assert capsys.readouterr().err == "GEMINI_API_KEY is not set, see .env.example\n"


def test_connection_error_gives_a_hint(monkeypatch, capsys):
    use_client(monkeypatch, FakeClient(APIConnectionError(request=REQUEST)))

    code = cli.main(["Hi"])

    assert code == 1
    assert "Can't reach http://fake/v1/" in capsys.readouterr().err


def test_chat_remembers_earlier_questions(monkeypatch, capsys):
    client = FakeClient(
        *refund_turn("CW-1001", "You get 90 EUR back."),
        completion(content="Tomorrow it is still 90 EUR."),
    )
    use_client(monkeypatch, client)
    type_in(monkeypatch, "How much for CW-1001?", "", "And tomorrow?", "exit")

    code = cli.main([])

    assert code == 0
    assert len(client.requests) == 3
    last_request = client.requests[2]
    assert last_request[1]["content"] == "How much for CW-1001?"
    assert last_request[-1]["content"] == "And tomorrow?"
    assert "Tomorrow it is still 90 EUR." in capsys.readouterr().out


def test_rate_limit_in_chat_drops_the_failed_turn(monkeypatch, capsys):
    rate_limited = RateLimitError(
        "rate limited", response=httpx2.Response(429, request=REQUEST), body=None
    )
    client = FakeClient(rate_limited, completion(content="We open at 08:00."))
    use_client(monkeypatch, client)
    type_in(monkeypatch, "First question", "When do you open?")

    code = cli.main([])

    captured = capsys.readouterr()
    assert code == 0
    assert "Rate limit reached" in captured.err
    assert "We open at 08:00." in captured.out
    assert [m["role"] for m in client.requests[1]] == ["system", "user"]
    assert client.requests[1][1]["content"] == "When do you open?"


def test_timeout_has_its_own_message(monkeypatch, capsys):
    use_client(monkeypatch, FakeClient(APITimeoutError(request=REQUEST)))

    code = cli.main(["Hi"])

    err = capsys.readouterr().err
    assert code == 1
    assert "didn't answer in time" in err
    assert "Ollama" not in err
