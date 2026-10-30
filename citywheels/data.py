import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
POLICIES_DIR = DATA_DIR / "policies"

SHOP_TZ = timezone(timedelta(hours=2))

# Fixed "current time" from the data README, so answers don't change between runs.
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
    booking_id = raw.strip().upper()
    # Customers often type just the number, e.g. "1002".
    if booking_id.isdigit():
        booking_id = f"CW-{booking_id}"
    return booking_id


def find_booking(booking_id: str) -> Booking | None:
    return load_bookings().get(normalize_booking_id(booking_id))
