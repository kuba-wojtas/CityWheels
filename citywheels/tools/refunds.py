from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from citywheels.data import NOW, SHOP_TZ, Booking, find_booking, normalize_booking_id


@dataclass(frozen=True)
class RefundQuote:
    hours_before_start: float
    refund_percent: int
    rental_refund_eur: float
    deposit_refund_eur: float
    booking_fee_kept_eur: float
    total_refund_eur: float
    rental_refund_method: str
    deposit_refund_method: str


def refund_percent(time_before_start: timedelta) -> int:
    if time_before_start >= timedelta(hours=48):
        return 100
    if time_before_start >= timedelta(hours=24):
        return 50
    return 0


def compute_refund(booking: Booking, cancel_at: datetime) -> RefundQuote:
    time_before_start = booking.start - cancel_at
    percent = refund_percent(time_before_start)
    # Float is fine here: all prices are whole or half euros, round() keeps cents clean.
    rental_refund = round(booking.rental_price_eur * percent / 100, 2)
    return RefundQuote(
        hours_before_start=round(time_before_start.total_seconds() / 3600, 1),
        refund_percent=percent,
        rental_refund_eur=rental_refund,
        deposit_refund_eur=booking.deposit_eur,
        booking_fee_kept_eur=booking.booking_fee_eur,
        total_refund_eur=round(rental_refund + booking.deposit_eur, 2),
        rental_refund_method=booking.paid_with,
        # Policy says the deposit comes back "the same way it was paid", but the bookings
        # don't record how the deposit was paid, so we don't guess.
        deposit_refund_method="same_as_paid",
    )


def calculate_refund(booking_id: str, cancel_at: str | None = None) -> dict:
    booking = find_booking(booking_id)
    if booking is None:
        return {"status": "not_found", "booking_id": normalize_booking_id(booking_id)}
    if booking.status != "confirmed":
        return {
            "status": "not_cancellable",
            "booking_id": booking.id,
            "booking_status": booking.status,
            "reason": f"booking is {booking.status}",
        }

    when = NOW
    if cancel_at is not None:
        try:
            when = datetime.fromisoformat(cancel_at)
        except ValueError:
            return {
                "status": "invalid_cancel_time",
                "booking_id": booking.id,
                "reason": f"not an ISO 8601 date: {cancel_at}",
            }
        if when.tzinfo is None:
            when = when.replace(tzinfo=SHOP_TZ)
        if when < NOW:
            return {
                "status": "invalid_cancel_time",
                "booking_id": booking.id,
                "reason": f"cancel time is in the past, now is {NOW.isoformat()}",
            }

    if when >= booking.start:
        return {
            "status": "not_cancellable",
            "booking_id": booking.id,
            "booking_status": booking.status,
            "reason": "rental has already started at the given cancel time",
        }

    quote = compute_refund(booking, when)
    return {
        "status": "ok",
        "booking_id": booking.id,
        "cancel_at": when.isoformat(),
        **asdict(quote),
    }
