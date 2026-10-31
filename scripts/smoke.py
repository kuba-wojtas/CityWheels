"""Quick check that a provider is configured and can call a tool.

Run: uv run python scripts/smoke.py [gemini|groq|ollama]
"""

import json
import sys

from dotenv import load_dotenv

from citywheels.llm import make_client
from citywheels.tools.bookings import get_booking

TOOL = {
    "type": "function",
    "function": {
        "name": "get_booking",
        "description": "Get one CityWheels booking by its number.",
        "parameters": {
            "type": "object",
            "properties": {"booking_id": {"type": "string"}},
            "required": ["booking_id"],
        },
    },
}


def main():
    load_dotenv()
    client, model = make_client(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"model: {model}")
    messages = [{"role": "user", "content": "What is the status of booking CW-1002?"}]

    first = client.chat.completions.create(model=model, messages=messages, tools=[TOOL])
    message = first.choices[0].message
    if not message.tool_calls:
        sys.exit(f"FAIL: model answered without calling the tool: {message.content}")
    call = message.tool_calls[0]
    print(f"tool call: {call.function.name}({call.function.arguments})")

    # Send the model's message back as it came, extra fields included. Gemini 3 puts a
    # thought signature there and rejects the next request without it.
    messages.append(message.model_dump(exclude_none=True))
    result = get_booking(**json.loads(call.function.arguments))
    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})

    second = client.chat.completions.create(model=model, messages=messages, tools=[TOOL])
    print(f"answer: {second.choices[0].message.content}")
    print("OK")


if __name__ == "__main__":
    main()
