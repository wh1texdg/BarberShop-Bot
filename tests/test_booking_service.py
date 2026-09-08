from datetime import date, time, timedelta, datetime

import pytest

from app.database.repositories.catalog_repo import MasterRepository, ServiceRepository
from app.database.repositories.schedule_repo import ScheduleRepository
from app.database.repositories.user_repo import UserRepository
from app.services.booking_service import (
    BookingService,
    CancellationNotAllowedError,
    SlotUnavailableError,
)


def _next_weekday(target_weekday: int) -> date:
    today = date.today()
    days_ahead = (target_weekday - today.weekday()) % 7
    days_ahead = days_ahead if days_ahead > 0 else 7
    return today + timedelta(days=days_ahead)


async def _setup(session, duration_minutes=60, weekday=0):
    user_repo = UserRepository(session)
    user = await user_repo.get_or_create(111, "client")

    master_repo = MasterRepository(session)
    master = await master_repo.create("Александр")

    service_repo = ServiceRepository(session)
    service = await service_repo.create("Стрижка", price=1200, duration_minutes=duration_minutes)

    await master_repo.assign_service(master.id, service.id)

    schedule_repo = ScheduleRepository(session)
    await schedule_repo.upsert_weekday(master.id, weekday, time(10, 0), time(20, 0))
    await session.commit()

    return user, master, service


@pytest.mark.asyncio
async def test_create_appointment_success(session):
    target_date = _next_weekday(0)
    user, master, service = await _setup(session)

    booking_service = BookingService(session)
    result = await booking_service.create_appointment(
        user.id, master.id, service.id, target_date, time(10, 0)
    )

    assert result.appointment.start_time == time(10, 0)
    assert result.appointment.end_time == time(11, 0)


@pytest.mark.asyncio
async def test_cannot_double_book_same_slot(session):
    target_date = _next_weekday(0)
    user, master, service = await _setup(session)

    booking_service = BookingService(session)
    await booking_service.create_appointment(user.id, master.id, service.id, target_date, time(15, 0))

    with pytest.raises(SlotUnavailableError):
        await booking_service.create_appointment(user.id, master.id, service.id, target_date, time(15, 0))


@pytest.mark.asyncio
async def test_90min_service_blocks_overlapping_start(session):
    """Per the TZ example: a 15:00-16:30 booking must block 16:00 but allow 16:30."""
    target_date = _next_weekday(0)
    user, master, service = await _setup(session, duration_minutes=90)

    booking_service = BookingService(session)
    await booking_service.create_appointment(user.id, master.id, service.id, target_date, time(15, 0))

    with pytest.raises(SlotUnavailableError):
        await booking_service.create_appointment(user.id, master.id, service.id, target_date, time(16, 0))

    # 16:30 doesn't overlap and should succeed.
    result = await booking_service.create_appointment(
        user.id, master.id, service.id, target_date, time(16, 30)
    )
    assert result.appointment.start_time == time(16, 30)


@pytest.mark.asyncio
async def test_cannot_book_outside_working_hours(session):
    target_date = _next_weekday(0)
    user, master, service = await _setup(session)

    booking_service = BookingService(session)
    with pytest.raises(SlotUnavailableError):
        await booking_service.create_appointment(user.id, master.id, service.id, target_date, time(19, 30))


@pytest.mark.asyncio
async def test_cancel_frees_the_slot(session):
    target_date = _next_weekday(0)
    user, master, service = await _setup(session)

    booking_service = BookingService(session)
    result = await booking_service.create_appointment(user.id, master.id, service.id, target_date, time(10, 0))
    await booking_service.cancel_appointment(result.appointment.id, user_id=user.id)

    # Slot should be bookable again after cancellation.
    result2 = await booking_service.create_appointment(user.id, master.id, service.id, target_date, time(10, 0))
    assert result2.appointment.id != result.appointment.id


@pytest.mark.asyncio
async def test_cannot_cancel_too_close_to_start(session):
    user_repo = UserRepository(session)
    user = await user_repo.get_or_create(222, "client2")

    master_repo = MasterRepository(session)
    master = await master_repo.create("Максим")

    service_repo = ServiceRepository(session)
    service = await service_repo.create("Борода", price=700, duration_minutes=30)
    await master_repo.assign_service(master.id, service.id)

    schedule_repo = ScheduleRepository(session)
    weekday = date.today().weekday()
    await schedule_repo.upsert_weekday(master.id, weekday, time(0, 0), time(23, 59))
    await session.commit()

    now = datetime.now()
    candidate = now + timedelta(minutes=60)

    minutes = candidate.hour * 60 + candidate.minute
    slot_minutes = 30
    rounded_minutes = ((minutes + slot_minutes - 1) // slot_minutes) * slot_minutes

    near_future = time(
        rounded_minutes // 60,
        rounded_minutes % 60,
    )

    booking_service = BookingService(session)
    result = await booking_service.create_appointment(
        user.id, master.id, service.id, date.today(), near_future
    )

    with pytest.raises(CancellationNotAllowedError):
        await booking_service.cancel_appointment(result.appointment.id, user_id=user.id)

    # Admin cancellation (user_id=None) bypasses the cutoff.
    await booking_service.cancel_appointment(result.appointment.id, user_id=None)


@pytest.mark.asyncio
async def test_cannot_cancel_someone_elses_appointment(session):
    target_date = _next_weekday(0)
    user, master, service = await _setup(session)
    other_user_repo = UserRepository(session)
    other_user = await other_user_repo.get_or_create(999, "someone_else")
    await session.commit()

    booking_service = BookingService(session)
    result = await booking_service.create_appointment(user.id, master.id, service.id, target_date, time(10, 0))

    with pytest.raises(SlotUnavailableError):
        await booking_service.cancel_appointment(result.appointment.id, user_id=other_user.id)
