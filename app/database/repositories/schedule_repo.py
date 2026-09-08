from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExceptionType, Schedule, ScheduleException


class ScheduleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_weekday_schedule(self, master_id: int, weekday: int) -> Schedule | None:
        result = await self.session.execute(
            select(Schedule).where(Schedule.master_id == master_id, Schedule.weekday == weekday)
        )
        return result.scalar_one_or_none()

    async def get_all_for_master(self, master_id: int) -> list[Schedule]:
        result = await self.session.execute(
            select(Schedule).where(Schedule.master_id == master_id).order_by(Schedule.weekday)
        )
        return list(result.scalars().all())

    async def upsert_weekday(
        self, master_id: int, weekday: int, start_time, end_time, break_start=None, break_end=None
    ) -> Schedule:
        schedule = await self.get_weekday_schedule(master_id, weekday)
        if schedule is None:
            schedule = Schedule(master_id=master_id, weekday=weekday)
            self.session.add(schedule)
        schedule.start_time = start_time
        schedule.end_time = end_time
        schedule.break_start = break_start
        schedule.break_end = break_end
        await self.session.flush()
        return schedule

    async def get_exception(self, master_id: int, on_date: date) -> ScheduleException | None:
        result = await self.session.execute(
            select(ScheduleException).where(
                ScheduleException.master_id == master_id, ScheduleException.date == on_date
            )
        )
        return result.scalar_one_or_none()

    async def add_exception(
        self, master_id: int, on_date: date, exc_type: ExceptionType, start_time=None, end_time=None
    ) -> ScheduleException:
        exception = await self.get_exception(master_id, on_date)
        if exception is None:
            exception = ScheduleException(master_id=master_id, date=on_date, type=exc_type)
            self.session.add(exception)
        exception.type = exc_type
        exception.start_time = start_time
        exception.end_time = end_time
        await self.session.flush()
        return exception
