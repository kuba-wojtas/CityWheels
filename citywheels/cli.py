import argparse
import sys

from dotenv import find_dotenv, load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from citywheels.agent import AgentResult, new_conversation, run_agent
from citywheels.llm import PROVIDERS, ConfigError, make_client

EXIT_WORDS = {"exit", "quit"}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="citywheels",
        description="CityWheels help desk agent. Ask one question, "
        "or leave the question out to start a conversation.",
    )
    parser.add_argument("question", nargs="?", help="question to ask")
    parser.add_argument("--provider", choices=list(PROVIDERS), help="overrides LLM_PROVIDER")
    parser.add_argument("--model", help="overrides LLM_MODEL")
    parser.add_argument("-q", "--quiet", action="store_true", help="hide the tool calls")
    return parser.parse_args(argv)


def print_result(result: AgentResult, quiet: bool) -> None:
    if not quiet:
        for call in result.tool_calls:
            print(f"  [tool] {call.name} {call.arguments} -> {call.result['status']}")
    print(result.answer)


def ask(client: OpenAI, model: str, messages: list[dict], question: str, quiet: bool) -> bool:
    turn_start = len(messages)
    try:
        result = run_agent(client, model, messages, question)
    except RateLimitError:
        error = "Rate limit reached, wait a minute and try again."
    except APIConnectionError:
        error = f"Can't reach {client.base_url}. If you use Ollama, is `ollama serve` running?"
    except APIStatusError as e:
        error = f"The provider returned an error ({e.status_code}): {e.message}"
    else:
        print_result(result, quiet)
        return True

    # Drop the failed turn, otherwise the next question would follow a half-finished one.
    del messages[turn_start:]
    print(error, file=sys.stderr)
    return False


def chat(client: OpenAI, model: str, quiet: bool) -> None:
    messages = new_conversation()
    print("CityWheels help desk. Type exit to quit.")
    while True:
        try:
            question = input("\n> ").strip()
        except EOFError:
            print()
            return
        if question.lower() in EXIT_WORDS:
            return
        if question:
            ask(client, model, messages, question, quiet)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(find_dotenv(usecwd=True))
    try:
        client, model = make_client(args.provider, args.model)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    try:
        if args.question:
            return 0 if ask(client, model, new_conversation(), args.question, args.quiet) else 1
        chat(client, model, args.quiet)
    except KeyboardInterrupt:
        print()
    return 0
