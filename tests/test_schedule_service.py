from datetime import date, time, timedelta

import pytest

from app.database.models import ExceptionType
from app.database.repositories.catalog_repo import MasterRepository, ServiceRepository
from app.database.repositories.schedule_repo import ScheduleRepository
from app.services.schedule_service import ScheduleService


async def _make_master_with_hours(session, weekday: int, start="10:00", end="20:00", break_start=None, break_end=None):
    master_repo = MasterRepository(session)
    master = await master_repo.create("Александр")
    schedule_repo = ScheduleRepository(session)
    await schedule_repo.upsert_weekday(
        master.id,
        weekday,
        time.fromisoformat(start),
        time.fromisoformat(end),
        time.fromisoformat(break_start) if break_start else None,
        time.fromisoformat(break_end) if break_end else None,
    )
    await session.commit()
    return master


def _next_weekday(target_weekday: int) -> date:
    today = date.today()
    days_ahead = (target_weekday - today.weekday()) % 7
    days_ahead = days_ahead if days_ahead > 0 else 7  # always a future date, avoids "past time today" edge cases
    return today + timedelta(days=days_ahead)


@pytest.mark.asyncio
async def test_no_schedule_means_no_slots(session):
    master_repo = MasterRepository(session)
    master = await master_repo.create("Максим")
    await session.commit()

    schedule_service = ScheduleService(session)
    slots = await schedule_service.get_available_slots(master.id, date.today() + timedelta(days=1), 60)
    assert slots == []


@pytest.mark.asyncio
async def test_basic_slots_within_working_hours(session):
    target_date = _next_weekday(0)
    master = await _make_master_with_hours(session, weekday=0, start="10:00", end="12:00")

    schedule_service = ScheduleService(session)
    slots = await schedule_service.get_available_slots(master.id, target_date, 60)

    assert time(10, 0) in slots
    assert time(11, 0) in slots
    # A 60-min service starting at 11:30 would end at 12:30, past closing time.
    assert time(11, 30) not in slots


@pytest.mark.asyncio
async def test_break_is_excluded_from_slots(session):
    target_date = _next_weekday(1)
    master = await _make_master_with_hours(
        session, weekday=1, start="10:00", end="20:00", break_start="14:00", break_end="15:00"
    )

    schedule_service = ScheduleService(session)
    slots = await schedule_service.get_available_slots(master.id, target_date, 60)

    assert time(13, 30) not in slots  # would run into the break
    assert time(14, 0) not in slots
    assert time(15, 0) in slots


@pytest.mark.asyncio
async def test_day_off_has_no_slots(session):
    target_date = _next_weekday(5)  # Saturday, never scheduled -> day off
    master_repo = MasterRepository(session)
    master = await master_repo.create("Никита")
    await session.commit()

    schedule_service = ScheduleService(session)
    slots = await schedule_service.get_available_slots(master.id, target_date, 60)
    assert slots == []


@pytest.mark.asyncio
async def test_exception_day_off_overrides_weekly_schedule(session):
    target_date = _next_weekday(0)
    master = await _make_master_with_hours(session, weekday=0, start="10:00", end="20:00")

    schedule_repo = ScheduleRepository(session)
    await schedule_repo.add_exception(master.id, target_date, ExceptionType.day_off)
    await session.commit()

    schedule_service = ScheduleService(session)
    slots = await schedule_service.get_available_slots(master.id, target_date, 60)
    assert slots == []


@pytest.mark.asyncio
async def test_exception_custom_hours_overrides_weekly_schedule(session):
    target_date = _next_weekday(0)
    master = await _make_master_with_hours(session, weekday=0, start="10:00", end="20:00")

    schedule_repo = ScheduleRepository(session)
    await schedule_repo.add_exception(
        master.id, target_date, ExceptionType.custom_hours, time(14, 0), time(18, 0)
    )
    await session.commit()

    schedule_service = ScheduleService(session)
    slots = await schedule_service.get_available_slots(master.id, target_date, 60)
    assert time(10, 0) not in slots
    assert time(14, 0) in slots
    assert time(17, 0) in slots


@pytest.mark.asyncio
async def test_past_date_has_no_slots(session):
    master = await _make_master_with_hours(session, weekday=date.today().weekday())
    schedule_service = ScheduleService(session)
    slots = await schedule_service.get_available_slots(master.id, date.today() - timedelta(days=1), 60)
    assert slots == []
