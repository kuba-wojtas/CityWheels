from pydantic import BaseModel, ConfigDict, Field

from citywheels.data import find_booking, normalize_booking_id


class GetBookingArgs(BaseModel):
    # Models sometimes send the number as 1002 instead of "1002".
    model_config = ConfigDict(coerce_numbers_to_str=True)
    booking_id: str = Field(description="Booking number, e.g. CW-1002")


def get_booking(booking_id: str) -> dict:
    booking = find_booking(booking_id)
    if booking is None:
        return {"status": "not_found", "booking_id": normalize_booking_id(booking_id)}
    return {"status": "ok", "booking": booking.to_dict()}
