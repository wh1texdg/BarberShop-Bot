from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Appointment, ExceptionType, MasterService, Schedule
from app.database.repositories.appointment_repo import AppointmentRepository
from app.database.repositories.schedule_repo import ScheduleRepository


def _add_minutes(t: time, minutes: int) -> time:
    base = datetime.combine(date.today(), t)
    result = base + timedelta(minutes=minutes)
    if result.date() != base.date():
        raise ValueError("Appointment cannot cross midnight")
    return result.time()


def _overlaps_break(start: time, end: time, break_start: time | None, break_end: time | None) -> bool:
    if not break_start or not break_end:
        return False
    return start < break_end and end > break_start


def _valid_period(start: time | None, end: time | None) -> bool:
    return start is not None and end is not None and start < end


class ScheduleService:
    """Resolves a master's working hours and computes valid free slots."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.schedule_repo = ScheduleRepository(session)
        self.appointment_repo = AppointmentRepository(session)

    async def get_working_hours(
        self, master_id: int, on_date: date
    ) -> tuple[time, time, time | None, time | None] | None:
        exception = await self.schedule_repo.get_exception(master_id, on_date)
        if exception:
            if exception.type == ExceptionType.day_off:
                return None
            if not _valid_period(exception.start_time, exception.end_time):
                return None
            return exception.start_time, exception.end_time, None, None

        schedule = await self.schedule_repo.get_weekday_schedule(master_id, on_date.weekday())
        if schedule is None or not _valid_period(schedule.start_time, schedule.end_time):
            return None

        break_start, break_end = schedule.break_start, schedule.break_end
        if break_start is not None or break_end is not None:
            if not _valid_period(break_start, break_end):
                break_start = break_end = None
        return schedule.start_time, schedule.end_time, break_start, break_end

    async def get_available_slots(
        self, master_id: int, on_date: date, duration_minutes: int
    ) -> list[time]:
        if on_date < settings.now_local().date() or duration_minutes <= 0:
            return []

        hours = await self.get_working_hours(master_id, on_date)
        if hours is None:
            return []
        work_start, work_end, break_start, break_end = hours

        busy = await self.appointment_repo.list_for_master_on_date(master_id, on_date)
        busy_ranges = [(a.start_time, a.end_time) for a in busy]

        now = settings.now_local()
        step = settings.slot_step_minutes
        if step <= 0:
            raise ValueError("SLOT_STEP_MINUTES must be positive")

        slots: list[time] = []
        cursor = work_start
        while cursor < work_end:
            try:
                slot_end = _add_minutes(cursor, duration_minutes)
            except ValueError:
                break
            if slot_end > work_end:
                break

            candidate_ok = not _overlaps_break(cursor, slot_end, break_start, break_end)
            if candidate_ok:
                candidate_ok = all(
                    not (cursor < busy_end and slot_end > busy_start)
                    for busy_start, busy_end in busy_ranges
                )

            if candidate_ok and on_date == now.date():
                candidate_ok = datetime.combine(on_date, cursor, tzinfo=settings.tzinfo) > now

            if candidate_ok:
                slots.append(cursor)
            try:
                cursor = _add_minutes(cursor, step)
            except ValueError:
                break

        return slots

    async def is_slot_still_free(
        self, master_id: int, on_date: date, start_time: time, duration_minutes: int
    ) -> bool:
        if on_date < settings.now_local().date():
            return False
        hours = await self.get_working_hours(master_id, on_date)
        if hours is None:
            return False
        work_start, work_end, break_start, break_end = hours
        try:
            end_time = _add_minutes(start_time, duration_minutes)
        except ValueError:
            return False

        if start_time < work_start or end_time > work_end:
            return False
        if _overlaps_break(start_time, end_time, break_start, break_end):
            return False
        if settings.slot_step_minutes <= 0:
            return False
        delta = datetime.combine(on_date, start_time) - datetime.combine(on_date, work_start)
        if delta.total_seconds() < 0 or delta.total_seconds() % (settings.slot_step_minutes * 60) != 0:
            return False
        if on_date == settings.now_local().date():
            if datetime.combine(on_date, start_time, tzinfo=settings.tzinfo) <= settings.now_local():
                return False
        return not await self.appointment_repo.has_overlap(master_id, on_date, start_time, end_time)
