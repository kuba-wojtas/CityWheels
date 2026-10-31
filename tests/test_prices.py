import pytest

from citywheels.data import load_bookings
from citywheels.tools.prices import quote_price


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
