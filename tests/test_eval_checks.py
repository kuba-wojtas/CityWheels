import pytest
from run_eval import check, recheck, unsupported_amounts

from citywheels.agent import ToolCall

REFUND = ToolCall(
    "calculate_refund",
    '{"booking_id": "CW-1002"}',
    {
        "status": "ok",
        "rental_refund_eur": 40.0,
        "deposit_refund_eur": 300.0,
        "total_refund_eur": 340.0,
    },
)
PRICES = ToolCall(
    "search_policies",
    '{"query": "e-bike price"}',
    {"status": "ok", "results": [{"text": "| Electric bike | 9 EUR | 40 EUR |"}]},
)


@pytest.mark.parametrize(
    "answer",
    [
        "You get €340.00 back.",
        "You get 340,00 € back.",
        "Total: EUR 340 (40 EUR rental + 300 EUR deposit).",
        "You get **340.0 EUR** back.",
    ],
)
def test_amounts_from_tool_results_are_supported(answer):
    assert unsupported_amounts(answer, [REFUND]) == []


def test_amounts_inside_policy_text_are_supported():
    assert unsupported_amounts("A day costs 40 EUR, an hour 9 EUR.", [PRICES]) == []


def test_amount_no_tool_returned_is_flagged():
    assert unsupported_amounts("You get 340 EUR back, plus 18 EUR late fee.", [REFUND]) == ["18"]


def test_plain_numbers_are_not_amounts():
    assert unsupported_amounts("Booking CW-1002 starts in 33 hours, 50% back.", [REFUND]) == []


def test_any_of_and_missing_text():
    case = {"must_contain": [["08:00", "8 am"], "Saturday"]}

    assert check(case, "We open at 8 am on Saturday.", []) == []
    assert check(case, "We open at 9 am.", []) == ["missing 08:00 / 8 am", "missing Saturday"]


def test_tools_and_forbidden_text():
    case = {"tools": ["calculate_refund"], "must_not_contain": ["Canberra"]}

    assert check(case, "It's Canberra.", []) == ["calculate_refund not called", "contains Canberra"]
    assert check(case, "You get 340 EUR.", [REFUND]) == []


def test_refusal_needs_staff_contact():
    case = {"refuse": True}

    assert check(case, "I can't help with that.", []) == ["no staff contact"]
    assert check(case, "I can't help. Contact help@citywheels.example.", []) == []


def test_clarify_needs_a_question_and_no_quote():
    case = {"clarify": True}
    quote = ToolCall("quote_price", "{}", {"status": "ok"})

    assert check(case, "How many bikes do you need?", []) == []
    assert check(case, "It costs 20 EUR.", [quote]) == [
        "didn't ask a question",
        "quoted a price without asking",
        "unsupported amounts 20",
    ]


def test_polish_answer_check():
    case = {"language": "pl"}

    assert check(case, "Otwieramy o 8:00 w sobotę.", []) == []
    assert check(case, "We open at 8:00 on Saturday.", []) == ["not in Polish"]


def test_typographic_apostrophes_and_hyphens_match_plain_ones():
    case = {"must_contain": [["couldn't find"], "CW-1234"]}

    assert check(case, "I couldn’t find booking CW‑1234.", []) == []


def test_recheck_rebuilds_tool_results_from_saved_arguments():
    case = {"id": "refund", "tools": ["calculate_refund"], "must_contain": ["340"]}
    run = {
        "results": [
            {
                "id": "refund",
                "answer": "You get 340 EUR back.",
                "tool_calls": [
                    {"name": "calculate_refund", "arguments": '{"booking_id": "CW-1002"}'}
                ],
                "failures": ["stale failure from an older checker"],
            },
            {"id": "refund", "answer": "", "tool_calls": [], "failures": ["request failed"]},
        ]
    }

    recheck(run, [case])

    assert run["results"][0]["failures"] == []
    assert run["results"][1]["failures"] == ["request failed"]
