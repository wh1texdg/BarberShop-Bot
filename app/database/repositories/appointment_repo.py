from datetime import date, time

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Appointment, AppointmentStatus, Service

ACTIVE_STATUSES = (AppointmentStatus.pending, AppointmentStatus.confirmed)


class AppointmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lock_master_day(self, master_id: int, appointment_date: date) -> None:
        """Serialize booking attempts for one master/day on PostgreSQL.

        A row lock alone does not protect the empty-day case because there are no
        existing rows to lock. A transaction-scoped advisory lock closes that gap.
        """
        bind = self.session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            key = f"barbershop:booking:{master_id}:{appointment_date.isoformat()}"
            await self.session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})

    async def list_for_master_on_date(self, master_id: int, appointment_date: date) -> list[Appointment]:
        result = await self.session.execute(
            select(Appointment)
            .where(
                Appointment.master_id == master_id,
                Appointment.appointment_date == appointment_date,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
            .with_for_update()
        )
        return list(result.scalars().all())

    async def has_overlap(self, master_id: int, appointment_date: date, start_time: time, end_time: time) -> bool:
        result = await self.session.execute(
            select(Appointment.id).where(
                Appointment.master_id == master_id,
                Appointment.appointment_date == appointment_date,
                Appointment.status.in_(ACTIVE_STATUSES),
                and_(Appointment.start_time < end_time, Appointment.end_time > start_time),
            )
        )
        return result.first() is not None

    async def create(
        self,
        user_id: int,
        master_id: int,
        service_id: int,
        appointment_date: date,
        start_time: time,
        end_time: time,
        price_at_booking,
    ) -> Appointment:
        appointment = Appointment(
            user_id=user_id,
            master_id=master_id,
            service_id=service_id,
            appointment_date=appointment_date,
            start_time=start_time,
            end_time=end_time,
            price_at_booking=price_at_booking,
            status=AppointmentStatus.confirmed,
        )
        self.session.add(appointment)
        await self.session.flush()
        return appointment

    async def get(self, appointment_id: int) -> Appointment | None:
        result = await self.session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.master),
                selectinload(Appointment.service),
                selectinload(Appointment.user),
                selectinload(Appointment.review),
            )
        )
        return result.scalar_one_or_none()

    async def list_upcoming_for_user(self, user_id: int, today: date) -> list[Appointment]:
        result = await self.session.execute(
            select(Appointment)
            .where(
                Appointment.user_id == user_id,
                Appointment.appointment_date >= today,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
            .options(selectinload(Appointment.master), selectinload(Appointment.service))
            .order_by(Appointment.appointment_date, Appointment.start_time)
        )
        return list(result.scalars().all())

    async def list_history_for_user(self, user_id: int) -> list[Appointment]:
        result = await self.session.execute(
            select(Appointment)
            .where(
                Appointment.user_id == user_id,
                or_(
                    Appointment.status.in_((AppointmentStatus.completed, AppointmentStatus.cancelled, AppointmentStatus.no_show)),
                    Appointment.appointment_date < today_local(),
                ),
            )
            .options(selectinload(Appointment.master), selectinload(Appointment.service), selectinload(Appointment.review))
            .order_by(Appointment.appointment_date.desc(), Appointment.start_time.desc())
        )
        return list(result.scalars().all())

    async def list_for_date(self, appointment_date: date) -> list[Appointment]:
        result = await self.session.execute(
            select(Appointment)
            .where(
                Appointment.appointment_date == appointment_date,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
            .options(selectinload(Appointment.master), selectinload(Appointment.service), selectinload(Appointment.user))
            .order_by(Appointment.start_time)
        )
        return list(result.scalars().all())

    async def list_all_for_date(self, appointment_date: date) -> list[Appointment]:
        result = await self.session.execute(
            select(Appointment)
            .where(Appointment.appointment_date == appointment_date)
            .options(selectinload(Appointment.master), selectinload(Appointment.service), selectinload(Appointment.user))
            .order_by(Appointment.start_time)
        )
        return list(result.scalars().all())

    async def list_future_active(self, start_date: date, days: int) -> list[Appointment]:
        end_date = start_date.fromordinal(start_date.toordinal() + days)
        result = await self.session.execute(
            select(Appointment)
            .where(
                Appointment.appointment_date >= start_date,
                Appointment.appointment_date < end_date,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
            .options(selectinload(Appointment.master), selectinload(Appointment.service), selectinload(Appointment.user))
            .order_by(Appointment.appointment_date, Appointment.start_time)
        )
        return list(result.scalars().all())

    async def cancel(self, appointment: Appointment) -> None:
        appointment.status = AppointmentStatus.cancelled
        await self.session.flush()

    async def set_status(self, appointment: Appointment, status: AppointmentStatus) -> None:
        appointment.status = status
        await self.session.flush()

    async def stats(self, start_date: date, end_date: date) -> dict:
        base_filter = (
            Appointment.appointment_date >= start_date,
            Appointment.appointment_date < end_date,
        )
        status_result = await self.session.execute(
            select(Appointment.status, func.count(Appointment.id))
            .where(*base_filter)
            .group_by(Appointment.status)
        )
        statuses = {status: count for status, count in status_result.all()}

        revenue_result = await self.session.execute(
            select(func.coalesce(func.sum(Appointment.price_at_booking), 0))
            .where(*base_filter, Appointment.status == AppointmentStatus.completed)
        )
        revenue = revenue_result.scalar_one()

        service_result = await self.session.execute(
            select(Service.name, func.count(Appointment.id))
            .join(Service, Service.id == Appointment.service_id)
            .where(*base_filter, Appointment.status == AppointmentStatus.completed)
            .group_by(Service.id, Service.name)
            .order_by(func.count(Appointment.id).desc())
        )
        popular = service_result.all()

        return {"statuses": statuses, "revenue": revenue, "popular": popular}


def today_local() -> date:
    from app.config import settings
    return settings.now_local().date()
