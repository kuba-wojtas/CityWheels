from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import BaseModel, Field

# Copied from data/policies/prices.md. test_prices.py checks them against every booking,
# so a change in the price list that isn't made here shows up as a failing test.
HOURLY_EUR = {"city": 4.0, "e-bike": 9.0, "kids": 2.0}
DAILY_EUR = {"city": 20.0, "e-bike": 40.0, "kids": 10.0}
DEPOSIT_EUR = {"city": 50.0, "e-bike": 150.0, "kids": 30.0}
ADD_ON_PER_DAY_EUR = {"child_seat": 3.0, "extra_lock": 0.0, "helmet": 0.0}
ONLINE_BOOKING_FEE_EUR = 2.0
WEEKLY_DISCOUNT = 0.15

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
