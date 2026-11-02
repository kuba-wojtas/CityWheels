from fakes import FakeClient, completion, tool_call, tool_messages

from citywheels.agent import (
    GIVE_UP_ANSWER,
    MAX_STEPS,
    TOOL_SCHEMAS,
    TOOLS,
    new_conversation,
    run_agent,
    run_tool,
)


def test_tool_call_round_trip():
    client = FakeClient(
        completion(tool_calls=[tool_call("c1", "get_booking", {"booking_id": "CW-1002"})]),
        completion(content="Booking CW-1002 is confirmed."),
    )
    messages = new_conversation()

    result = run_agent(client, "fake", messages, "What is the status of CW-1002?")

    assert result.answer == "Booking CW-1002 is confirmed."
    assert result.steps == 2
    assert [c.name for c in result.tool_calls] == ["get_booking"]
    assert result.tool_calls[0].result["booking"]["status"] == "confirmed"
    assert (result.input_tokens, result.output_tokens) == (200, 20)

    # The second request carries the real tool result back to the model.
    second = client.requests[1]
    assert second[-1]["role"] == "tool"
    assert second[-1]["tool_call_id"] == "c1"
    assert tool_messages(second)[0]["booking"]["bikes"] == 2

    # The thought signature survives in the history.
    assistant = second[-2]
    assert assistant["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig-123"

    assert messages[-1] == {"role": "assistant", "content": "Booking CW-1002 is confirmed."}


def test_refund_amount_comes_from_code():
    client = FakeClient(
        completion(tool_calls=[tool_call("c1", "calculate_refund", {"booking_id": "CW-1002"})]),
        completion(content="You get 340 EUR back."),
    )

    run_agent(client, "fake", new_conversation(), "How much do I get back for CW-1002?")

    refund = tool_messages(client.requests[1])[0]
    assert refund["refund_percent"] == 50
    assert refund["total_refund_eur"] == 340.0


def test_unknown_booking_reaches_the_model_as_not_found():
    client = FakeClient(
        completion(tool_calls=[tool_call("c1", "get_booking", {"booking_id": "CW-9999"})]),
        completion(content="I couldn't find that booking."),
    )

    result = run_agent(client, "fake", new_conversation(), "Status of CW-9999?")

    assert tool_messages(client.requests[1])[0] == {"status": "not_found", "booking_id": "CW-9999"}
    assert result.answer == "I couldn't find that booking."


def test_bad_tool_calls_are_reported_back_and_the_loop_goes_on():
    client = FakeClient(
        completion(
            tool_calls=[
                tool_call("c1", "get_booking", {}),
                tool_call("c2", "cancel_booking", {"booking_id": "CW-1002"}),
                tool_call("c3", "quote_price", "{not json"),
            ]
        ),
        completion(content="Sorry, something went wrong."),
    )

    result = run_agent(client, "fake", new_conversation(), "Cancel CW-1002")

    missing, unknown, broken = tool_messages(client.requests[1])
    assert missing["status"] == "invalid_arguments"
    assert "booking_id" in missing["errors"][0]
    assert unknown == {"status": "unknown_tool", "name": "cancel_booking"}
    assert broken["status"] == "invalid_arguments"
    assert result.steps == 2


def test_gives_up_after_max_steps():
    looping = [
        completion(tool_calls=[tool_call(f"c{i}", "search_policies", {"query": "price"})])
        for i in range(MAX_STEPS)
    ]
    client = FakeClient(*looping)
    messages = new_conversation()

    result = run_agent(client, "fake", messages, "How much?")

    assert result.gave_up
    assert result.answer == GIVE_UP_ANSWER
    assert len(client.requests) == MAX_STEPS
    assert messages[-1] == {"role": "assistant", "content": GIVE_UP_ANSWER}


def test_follow_up_question_sees_the_earlier_turn():
    client = FakeClient(
        completion(tool_calls=[tool_call("c1", "calculate_refund", {"booking_id": "CW-1001"})]),
        completion(content="You get 90 EUR back."),
        completion(content="Tomorrow you would still get 90 EUR."),
    )
    messages = new_conversation()

    run_agent(client, "fake", messages, "How much for cancelling CW-1001?")
    run_agent(client, "fake", messages, "And if I cancel tomorrow?")

    third = client.requests[2]
    assert [m["role"] for m in third] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]
    assert third[-1]["content"] == "And if I cancel tomorrow?"
    # The refund from the first turn is still there for the model to build on.
    assert tool_messages(third)[0]["total_refund_eur"] == 90.0


def test_booking_number_sent_as_a_number_is_accepted():
    assert run_tool("get_booking", '{"booking_id": 1002}')["booking"]["id"] == "CW-1002"


def test_quote_price_rejects_unknown_bike_type_before_running():
    result = run_tool("quote_price", '{"bike_type": "mountain", "duration_hours": 3, "bikes": 1}')

    assert result["status"] == "invalid_arguments"
    assert "bike_type" in result["errors"][0]


def test_every_tool_has_a_schema():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}

    assert names == {
        "search_policies",
        "get_booking",
        "calculate_refund",
        "quote_price",
        "calculate_late_fee",
    }


def test_tool_crash_becomes_an_error_result(monkeypatch):
    def broken(booking_id):
        raise OverflowError("boom")

    monkeypatch.setitem(TOOLS, "get_booking", (broken, *TOOLS["get_booking"][1:]))
    client = FakeClient(
        completion(tool_calls=[tool_call("c1", "get_booking", {"booking_id": "CW-1002"})]),
        completion(content="Sorry, please contact the staff."),
    )

    result = run_agent(client, "fake", new_conversation(), "Status of CW-1002?")

    assert tool_messages(client.requests[1]) == [{"status": "tool_error", "name": "get_booking"}]
    assert result.answer == "Sorry, please contact the staff."


def test_out_of_range_quote_is_rejected_before_running():
    result = run_tool("quote_price", '{"bike_type": "city", "duration_hours": 1e400, "bikes": 1}')

    assert result["status"] == "invalid_arguments"


def test_empty_response_from_provider_gives_up():
    empty = completion(content="x")
    empty.choices = []
    messages = new_conversation()

    result = run_agent(FakeClient(empty), "fake", messages, "Hi")

    assert result.gave_up
    assert messages[-1]["content"] == GIVE_UP_ANSWER
