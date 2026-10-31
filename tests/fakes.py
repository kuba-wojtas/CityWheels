import copy
import json
from types import SimpleNamespace

from openai.types.chat import ChatCompletion

from citywheels.agent import TOOL_SCHEMAS


def completion(content=None, tool_calls=None) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "fake",
            "object": "chat.completion",
            "created": 0,
            "model": "fake",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                    "message": {"role": "assistant", "content": content, "tool_calls": tool_calls},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
        }
    )


def tool_call(call_id: str, name: str, arguments) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
        },
        "extra_content": {"google": {"thought_signature": "sig-123"}},
    }


def tool_messages(request: list[dict]) -> list[dict]:
    return [json.loads(m["content"]) for m in request if m["role"] == "tool"]


class FakeClient:
    """Replays scripted responses (or raises scripted errors) and records each request."""

    base_url = "http://fake/v1/"

    def __init__(self, *responses: ChatCompletion | Exception):
        self.responses = list(responses)
        self.requests: list[list[dict]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, tools):
        assert tools == TOOL_SCHEMAS
        self.requests.append(copy.deepcopy(messages))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
