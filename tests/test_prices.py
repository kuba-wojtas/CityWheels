import pytest

from citywheels.data import load_bookings
from citywheels.tools.prices import calculate_late_fee, quote_price


@pytest.mark.parametrize("booking", load_bookings().values(), ids=lambda b: b.id)
def test_price_list_matches_every_booking(booking):
    hours = (booking.end - booking.start).total_seconds() / 3600

    result = quote_price(booking.bike_type, hours, booking.bikes, list(booking.add_ons))

    assert result["price_eur"] == booking.rental_price_eur
    assert result["deposit_eur"] == booking.deposit_eur
    assert booking.booking_fee_eur in (
        result["online_booking_fee_eur"],
        result["shop_booking_fee_eur"],
    )


def test_every_started_hour_is_charged():
    result = quote_price("city", 2.5, 1)

    assert result["charged_hours"] == 3
    assert result["price_eur"] == 12.0


def test_six_hours_is_still_hourly():
    # 6 x 4 EUR = 24 EUR, more than the 20 EUR day price. The price list says so.
    result = quote_price("city", 6, 1)

    assert result["charged_days"] == 0
    assert result["price_eur"] == 24.0


def test_over_six_hours_is_a_day():
    result = quote_price("city", 6 + 1 / 60, 1)

    assert result["charged_days"] == 1
    assert result["charged_hours"] == 0
    assert result["price_eur"] == 20.0


def test_whole_day_e_bike():
    result = quote_price("e-bike", 24, 1)

    assert result["charged_days"] == 1
    assert result["price_eur"] == 40.0
    assert result["deposit_eur"] == 150.0


def test_short_rest_after_full_day_is_hourly():
    result = quote_price("city", 26, 1)

    assert (result["charged_days"], result["charged_hours"]) == (1, 2)
    assert result["price_eur"] == 28.0


def test_long_rest_after_full_day_is_another_day():
    result = quote_price("city", 31, 1)

    assert (result["charged_days"], result["charged_hours"]) == (2, 0)
    assert result["price_eur"] == 40.0


def test_six_days_have_no_discount():
    result = quote_price("city", 6 * 24, 1)

    assert result["discount_eur"] == 0.0
    assert result["price_eur"] == 120.0


def test_seven_days_get_fifteen_percent_off():
    result = quote_price("city", 7 * 24, 1)

    assert result["rental_eur"] == 140.0
    assert result["discount_eur"] == 21.0
    assert result["price_eur"] == 119.0


def test_child_seat_is_charged_per_started_day():
    assert quote_price("city", 3, 1, ["child_seat"])["add_ons_eur"] == 3.0
    assert quote_price("city", 48, 1, ["child_seat"])["add_ons_eur"] == 6.0


def test_weekly_discount_covers_add_ons():
    result = quote_price("city", 7 * 24, 1, ["child_seat"])

    assert result["add_ons_eur"] == 21.0
    assert result["discount_eur"] == 24.15
    assert result["price_eur"] == 136.85


def test_free_add_ons_cost_nothing():
    assert quote_price("city", 3, 1, ["helmet", "extra_lock"])["add_ons_eur"] == 0.0


def test_price_and_deposit_scale_with_bikes():
    result = quote_price("kids", 3, 2)

    assert result["price_eur"] == 12.0
    assert result["deposit_eur"] == 60.0


def test_both_booking_fees_are_returned():
    result = quote_price("city", 3, 1)

    assert result["online_booking_fee_eur"] == 2.0
    assert result["shop_booking_fee_eur"] == 0.0


@pytest.mark.parametrize(
    "bike_type, hours, bikes, add_ons",
    [
        ("mountain", 3, 1, None),
        ("city", 0, 1, None),
        ("city", -2, 1, None),
        ("city", 3, 0, None),
        ("city", 3, 1, ["basket"]),
    ],
)
def test_invalid_input_is_rejected(bike_type, hours, bikes, add_ons):
    result = quote_price(bike_type, hours, bikes, add_ons)

    assert result["status"] == "invalid_input"
    assert result["reason"]


def test_late_fee_counts_every_started_hour():
    # CW-1008: one city bike, rental ends 12:00. 14:30 = 3 started hours x 1.5 x 4 EUR.
    result = calculate_late_fee("CW-1008", "2026-06-10T14:30:00+02:00")

    assert result["status"] == "ok"
    assert result["minutes_late"] == 150
    assert result["started_hours_late"] == 3
    assert result["fee_per_bike_per_hour_eur"] == 6.0
    assert result["late_fee_eur"] == 18.0


@pytest.mark.parametrize(
    "returned_at, fee",
    [
        ("2026-06-10T11:30:00+02:00", 0.0),
        ("2026-06-10T12:00:00+02:00", 0.0),
        ("2026-06-10T12:01", 6.0),
    ],
)
def test_late_fee_on_time_or_one_minute_late(returned_at, fee):
    assert calculate_late_fee("CW-1008", returned_at)["late_fee_eur"] == fee


def test_late_fee_is_per_bike():
    # CW-1002: two e-bikes, 1 started hour x 1.5 x 9 EUR x 2 bikes.
    result = calculate_late_fee("CW-1002", "2026-06-12T18:20:00+02:00")

    assert result["late_fee_eur"] == 27.0


@pytest.mark.parametrize("booking_id", ["CW-1005", "CW-1006"])
def test_late_fee_not_applicable_to_cancelled_or_completed(booking_id):
    assert calculate_late_fee(booking_id, "2026-06-10T14:00")["status"] == "not_applicable"


def test_late_fee_unknown_booking_and_bad_time():
    assert calculate_late_fee("CW-9999", "2026-06-10T14:00")["status"] == "not_found"
    assert calculate_late_fee("CW-1008", "at 2pm")["status"] == "invalid_return_time"
