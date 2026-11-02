import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
POLICIES_DIR = DATA_DIR / "policies"

SHOP_TZ = ZoneInfo("Europe/Warsaw")

# Fixed "current time" from data/README.md, so answers don't change between runs.
NOW = datetime(2026, 6, 10, 9, 0, tzinfo=SHOP_TZ)


@dataclass(frozen=True)
class Booking:
    id: str
    status: str
    bike_type: str
    bikes: int
    start: datetime
    end: datetime
    add_ons: tuple[str, ...]
    rental_price_eur: float
    booking_fee_eur: float
    deposit_eur: float
    paid_with: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["start"] = self.start.isoformat()
        data["end"] = self.end.isoformat()
        data["add_ons"] = list(self.add_ons)
        return data


@cache
def load_bookings() -> dict[str, Booking]:
    raw = json.loads((DATA_DIR / "bookings.json").read_text(encoding="utf-8"))
    bookings = [
        Booking(
            **{
                **item,
                "start": datetime.fromisoformat(item["start"]),
                "end": datetime.fromisoformat(item["end"]),
                "add_ons": tuple(item["add_ons"]),
            }
        )
        for item in raw
    ]
    return {b.id: b for b in bookings}


def normalize_booking_id(raw: str) -> str:
    # Customers type "1002", "cw1002" or "CW 1002" as often as "CW-1002". Some models
    # write the hyphen as a non-breaking one (U+2011).
    number = re.sub(r"[\s\-‐‑]", "", raw).upper().removeprefix("CW")
    if number.isdigit():
        return f"CW-{number}"
    return raw.strip().upper()


def find_booking(booking_id: str) -> Booking | None:
    return load_bookings().get(normalize_booking_id(booking_id))


def parse_shop_time(text: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    # A time without a zone means shop time, that's what a customer saying "at 10:00" means.
    return when if when.tzinfo else when.replace(tzinfo=SHOP_TZ)
