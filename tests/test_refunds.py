from datetime import datetime

import pytest

from citywheels.data import NOW, Booking, parse_shop_time
from citywheels.tools.refunds import calculate_refund, compute_refund


@pytest.mark.parametrize(
    "booking_id, hours, percent, rental, deposit, fee_kept, total",
    [
        ("CW-1001", 73.0, 100, 40.0, 50.0, 2.0, 90.0),
        ("CW-1002", 33.0, 50, 40.0, 300.0, 2.0, 340.0),
        ("CW-1003", 6.0, 0, 0.0, 50.0, 2.0, 50.0),
        ("CW-1004", 240.0, 100, 23.0, 50.0, 2.0, 73.0),
        ("CW-1007", 48.0, 100, 36.0, 150.0, 2.0, 186.0),
        ("CW-1009", 121.0, 100, 119.0, 50.0, 2.0, 169.0),
        ("CW-1010", 24.0, 50, 20.0, 150.0, 0.0, 170.0),
    ],
)
def test_refund_for_confirmed_bookings_now(
    booking_id, hours, percent, rental, deposit, fee_kept, total
):
    result = calculate_refund(booking_id)

    assert result["status"] == "ok"
    assert result["cancel_at"] == "2026-06-10T09:00:00+02:00"
    assert result["hours_before_start"] == hours
    assert result["refund_percent"] == percent
    assert result["rental_refund_eur"] == rental
    assert result["deposit_refund_eur"] == deposit
    assert result["booking_fee_kept_eur"] == fee_kept
    assert result["total_refund_eur"] == total


@pytest.mark.parametrize(
    "booking_id, percent",
    [
        ("CW-1007", 50),  # starts in 47h59m
        ("CW-1010", 0),  # starts in 23h59m
    ],
)
def test_one_minute_past_boundary_drops_a_tier(booking_id, percent):
    result = calculate_refund(booking_id, cancel_at="2026-06-10T09:01:00+02:00")

    assert result["refund_percent"] == percent
    assert result["hours_before_start"] < (48 if percent == 50 else 24)


@pytest.mark.parametrize(
    "booking_id, status",
    [("CW-1005", "cancelled"), ("CW-1006", "completed"), ("CW-1008", "in_progress")],
)
def test_only_confirmed_bookings_can_be_cancelled(booking_id, status):
    result = calculate_refund(booking_id)

    assert result["status"] == "not_cancellable"
    assert result["booking_status"] == status
    assert "total_refund_eur" not in result


def test_unknown_booking_is_not_found():
    assert calculate_refund("CW-9999") == {"status": "not_found", "booking_id": "CW-9999"}


def test_card_booking_refund_methods():
    result = calculate_refund("CW-1001")

    assert result["rental_refund_method"] == "card"
    assert result["deposit_refund_method"] == "same_as_paid"


def test_voucher_booking_refunds_rental_as_voucher():
    result = calculate_refund("CW-1004")

    assert result["rental_refund_method"] == "voucher"
    assert result["deposit_refund_method"] == "same_as_paid"


def test_cancel_tomorrow_keeps_full_refund_for_far_booking():
    result = calculate_refund("CW-1001", cancel_at="2026-06-11T09:00:00+02:00")

    assert result["hours_before_start"] == 49.0
    assert result["refund_percent"] == 100
    assert result["total_refund_eur"] == 90.0


def test_cancel_tomorrow_loses_rental_refund_for_close_booking():
    result = calculate_refund("CW-1002", cancel_at="2026-06-11T09:00:00+02:00")

    assert result["hours_before_start"] == 9.0
    assert result["refund_percent"] == 0
    assert result["total_refund_eur"] == 300.0


def test_cancel_time_without_zone_is_shop_time():
    result = calculate_refund("CW-1002", cancel_at="2026-06-11T09:00")

    assert result["cancel_at"] == "2026-06-11T09:00:00+02:00"
    assert result["hours_before_start"] == 9.0


def test_cancel_time_in_other_zone_is_converted():
    result = calculate_refund("CW-1002", cancel_at="2026-06-11T07:00:00+00:00")

    assert result["hours_before_start"] == 9.0


@pytest.mark.parametrize("cancel_at", ["tomorrow", "11.06.2026", ""])
def test_unparseable_cancel_time_is_rejected(cancel_at):
    assert calculate_refund("CW-1001", cancel_at=cancel_at)["status"] == "invalid_cancel_time"


def test_cancel_time_in_the_past_is_rejected():
    result = calculate_refund("CW-1001", cancel_at="2026-06-09T09:00:00+02:00")

    assert result["status"] == "invalid_cancel_time"


@pytest.mark.parametrize("cancel_at", ["2026-06-10T15:00:00+02:00", "2026-06-10T16:00:00+02:00"])
def test_cancel_at_or_after_start_is_not_cancellable(cancel_at):
    result = calculate_refund("CW-1003", cancel_at=cancel_at)

    assert result["status"] == "not_cancellable"
    assert result["booking_status"] == "confirmed"


def make_booking(**overrides) -> Booking:
    fields = {
        "id": "CW-TEST",
        "status": "confirmed",
        "bike_type": "city",
        "bikes": 1,
        "start": datetime.fromisoformat("2026-06-12T10:00:00+02:00"),
        "end": datetime.fromisoformat("2026-06-12T14:00:00+02:00"),
        "add_ons": (),
        "rental_price_eur": 25.5,
        "booking_fee_eur": 2.0,
        "deposit_eur": 50.0,
        "paid_with": "card",
    }
    return Booking(**(fields | overrides))


def test_half_refund_keeps_cents():
    booking = make_booking(start=datetime.fromisoformat("2026-06-11T10:00:00+02:00"))

    quote = compute_refund(booking, cancel_at=NOW)

    assert quote.refund_percent == 50
    assert quote.rental_refund_eur == 12.75
    assert quote.total_refund_eur == 62.75


def test_booking_fee_is_never_refunded():
    quote = compute_refund(make_booking(booking_fee_eur=5.0), cancel_at=NOW)

    assert quote.refund_percent == 100
    assert quote.booking_fee_kept_eur == 5.0
    assert quote.total_refund_eur == 75.5


def test_date_without_time_means_midnight():
    # Documented behaviour: "2026-06-11" is 00:00 shop time, 18h before CW-1002 starts.
    result = calculate_refund("CW-1002", cancel_at="2026-06-11")

    assert result["cancel_at"] == "2026-06-11T00:00:00+02:00"
    assert result["refund_percent"] == 0


def test_shop_time_follows_warsaw_winter_time():
    assert parse_shop_time("2026-12-01T10:00").isoformat() == "2026-12-01T10:00:00+01:00"
