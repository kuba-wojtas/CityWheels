from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from citywheels.data import find_booking, normalize_booking_id, parse_shop_time

# Copied from data/policies/prices.md. test_prices.py checks them against every booking,
# so a change in the price list that isn't made here shows up as a failing test.
HOURLY_EUR = {"city": 4.0, "e-bike": 9.0, "kids": 2.0}
DAILY_EUR = {"city": 20.0, "e-bike": 40.0, "kids": 10.0}
DEPOSIT_EUR = {"city": 50.0, "e-bike": 150.0, "kids": 30.0}
ADD_ON_PER_DAY_EUR = {"child_seat": 3.0, "extra_lock": 0.0, "helmet": 0.0}
ONLINE_BOOKING_FEE_EUR = 2.0
WEEKLY_DISCOUNT = 0.15
LATE_FEE_HOURLY_MULTIPLIER = 1.5

MINUTES_PER_DAY = 24 * 60


class QuotePriceArgs(BaseModel):
    bike_type: Literal["city", "e-bike", "kids"]
    duration_hours: float = Field(description="Rental length in hours, e.g. 24 for a day")
    bikes: int = Field(description="Number of bikes")
    add_ons: list[Literal["child_seat", "extra_lock", "helmet"]] = Field(default_factory=list)


@dataclass(frozen=True)
class PriceQuote:
    charged_days: int
    charged_hours: int
    rental_eur: float
    add_ons_eur: float
    discount_eur: float
    price_eur: float
    deposit_eur: float


def compute_price(
    bike_type: str, duration_hours: float, bikes: int, add_ons: list[str]
) -> PriceQuote:
    minutes = round(duration_hours * 60)
    days, rest = divmod(minutes, MINUTES_PER_DAY)
    hours = 0
    # The price list doesn't say how to charge what's left after full days (e.g. 26h).
    # We apply the same rule as for a single rental: over 6h is a day, otherwise started hours.
    if rest > 6 * 60:
        days += 1
    elif rest > 0:
        hours = -(-rest // 60)

    rental = bikes * (days * DAILY_EUR[bike_type] + hours * HOURLY_EUR[bike_type])
    add_on_days = days + (1 if hours else 0)
    add_ons_total = sum(ADD_ON_PER_DAY_EUR[a] * add_on_days for a in add_ons)
    # README defines the rental price as "with add-ons", so the discount covers add-ons too.
    discount = 0.0
    if minutes >= 7 * MINUTES_PER_DAY:
        discount = round((rental + add_ons_total) * WEEKLY_DISCOUNT, 2)

    return PriceQuote(
        charged_days=days,
        charged_hours=hours,
        rental_eur=rental,
        add_ons_eur=add_ons_total,
        discount_eur=discount,
        price_eur=round(rental + add_ons_total - discount, 2),
        deposit_eur=bikes * DEPOSIT_EUR[bike_type],
    )


def quote_price(
    bike_type: str, duration_hours: float, bikes: int, add_ons: list[str] | None = None
) -> dict:
    add_ons = add_ons or []
    if bike_type not in HOURLY_EUR:
        return {
            "status": "invalid_input",
            "reason": f"unknown bike type {bike_type!r}, expected one of {list(HOURLY_EUR)}",
        }
    if duration_hours <= 0:
        return {"status": "invalid_input", "reason": "duration_hours must be more than 0"}
    if bikes < 1:
        return {"status": "invalid_input", "reason": "bikes must be at least 1"}
    unknown = [a for a in add_ons if a not in ADD_ON_PER_DAY_EUR]
    if unknown:
        return {
            "status": "invalid_input",
            "reason": f"unknown add-ons {unknown}, expected some of {list(ADD_ON_PER_DAY_EUR)}",
        }

    quote = compute_price(bike_type, duration_hours, bikes, add_ons)
    return {
        "status": "ok",
        "bike_type": bike_type,
        "duration_hours": duration_hours,
        "bikes": bikes,
        "add_ons": add_ons,
        **asdict(quote),
        "online_booking_fee_eur": ONLINE_BOOKING_FEE_EUR,
        "shop_booking_fee_eur": 0.0,
    }


class CalculateLateFeeArgs(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)
    booking_id: str = Field(description="Booking number, e.g. CW-1008")
    returned_at: str = Field(description="When the bikes come back, ISO 8601 date and time")


def calculate_late_fee(booking_id: str, returned_at: str) -> dict:
    booking = find_booking(booking_id)
    if booking is None:
        return {"status": "not_found", "booking_id": normalize_booking_id(booking_id)}
    if booking.status not in ("confirmed", "in_progress"):
        return {
            "status": "not_applicable",
            "booking_id": booking.id,
            "booking_status": booking.status,
        }
    returned = parse_shop_time(returned_at)
    if returned is None:
        return {
            "status": "invalid_return_time",
            "booking_id": booking.id,
            "reason": f"not an ISO 8601 date: {returned_at}",
        }

    minutes_late = max(0, round((returned - booking.end).total_seconds() / 60))
    started_hours = -(-minutes_late // 60)
    fee_per_hour = LATE_FEE_HOURLY_MULTIPLIER * HOURLY_EUR[booking.bike_type]
    return {
        "status": "ok",
        "booking_id": booking.id,
        "rental_end": booking.end.isoformat(),
        "returned_at": returned.isoformat(),
        "minutes_late": minutes_late,
        "started_hours_late": started_hours,
        "fee_per_bike_per_hour_eur": fee_per_hour,
        "bikes": booking.bikes,
        "late_fee_eur": round(booking.bikes * fee_per_hour * started_hours, 2),
        "deposit_eur": booking.deposit_eur,
    }
