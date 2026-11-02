import pytest

from citywheels.tools.bookings import get_booking


def test_returns_booking_details():
    result = get_booking("CW-1002")

    assert result["status"] == "ok"
    booking = result["booking"]
    assert booking["id"] == "CW-1002"
    assert booking["status"] == "confirmed"
    assert booking["bike_type"] == "e-bike"
    assert booking["bikes"] == 2
    assert booking["rental_price_eur"] == 80.0
    assert booking["deposit_eur"] == 300.0
    assert booking["start"] == "2026-06-11T18:00:00+02:00"
    assert booking["add_ons"] == []


def test_returns_add_ons():
    assert get_booking("CW-1004")["booking"]["add_ons"] == ["child_seat"]


@pytest.mark.parametrize(
    "raw", ["cw-1002", "  CW-1002 ", "1002", " 1002", "cw1002", "CW 1002", "CW\u20111002"]
)
def test_accepts_loose_booking_numbers(raw):
    result = get_booking(raw)

    assert result["status"] == "ok"
    assert result["booking"]["id"] == "CW-1002"


def test_unknown_booking_is_not_found():
    assert get_booking("CW-9999") == {"status": "not_found", "booking_id": "CW-9999"}


@pytest.mark.parametrize("raw", ["", "hello", "CW-", "CW-10O2"])
def test_garbage_booking_number_is_not_found(raw):
    assert get_booking(raw)["status"] == "not_found"


def test_cancelled_booking_is_still_returned():
    result = get_booking("CW-1005")

    assert result["status"] == "ok"
    assert result["booking"]["status"] == "cancelled"
