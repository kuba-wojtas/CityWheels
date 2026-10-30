from citywheels.data import find_booking, normalize_booking_id


def get_booking(booking_id: str) -> dict:
    booking = find_booking(booking_id)
    if booking is None:
        return {"status": "not_found", "booking_id": normalize_booking_id(booking_id)}
    return {"status": "ok", "booking": booking.to_dict()}
