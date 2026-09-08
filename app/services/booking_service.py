from dataclasses import dataclass
from datetime import date, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Appointment, AppointmentStatus, Service
from app.database.repositories.appointment_repo import AppointmentRepository
from app.database.repositories.catalog_repo import MasterRepository, ServiceRepository
from app.services.schedule_service import ScheduleService, _add_minutes


class SlotUnavailableError(Exception):
    """Raised when the requested slot is not valid or is no longer free."""


class CancellationNotAllowedError(Exception):
    """Raised when a cancellation is attempted too close to the appointment start."""


@dataclass
class BookingResult:
    appointment: Appointment
    service: Service


class BookingService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.appointment_repo = AppointmentRepository(session)
        self.service_repo = ServiceRepository(session)
        self.master_repo = MasterRepository(session)
        self.schedule_service = ScheduleService(session)

    async def create_appointment(
        self, user_id: int, master_id: int, service_id: int, on_date: date, start_time: time
    ) -> BookingResult:
        service = await self.service_repo.get(service_id)
        master = await self.master_repo.get(master_id)
        if service is None or not service.is_active:
            raise SlotUnavailableError("Услуга больше недоступна.")
        if master is None or not master.is_active:
            raise SlotUnavailableError("Выбранный мастер больше недоступен.")
        if not await self.master_repo.has_service(master_id, service_id):
            raise SlotUnavailableError("Этот мастер не оказывает выбранную услугу.")

        try:
            end_time = _add_minutes(start_time, service.duration_minutes)
        except ValueError:
            raise SlotUnavailableError("Услуга не может заканчиваться на следующий день.") from None

        # Serialize all bookings for this master/day. This is important even when
        # there are currently zero appointments (row locks cannot lock a missing row).
        await self.appointment_repo.lock_master_day(master_id, on_date)
        await self.appointment_repo.list_for_master_on_date(master_id, on_date)

        still_free = await self.schedule_service.is_slot_still_free(
            master_id, on_date, start_time, service.duration_minutes
        )
        if not still_free:
            raise SlotUnavailableError("Похоже, этот слот только что заняли. Выберите другое время.")

        appointment = await self.appointment_repo.create(
            user_id=user_id,
            master_id=master_id,
            service_id=service_id,
            appointment_date=on_date,
            start_time=start_time,
            end_time=end_time,
            price_at_booking=service.price,
        )
        await self.session.commit()
        return BookingResult(appointment=appointment, service=service)

    async def cancel_appointment(self, appointment_id: int, user_id: int | None = None) -> Appointment:
        appointment = await self.appointment_repo.get(appointment_id)
        if appointment is None:
            raise SlotUnavailableError("Запись не найдена.")
        if user_id is not None and appointment.user_id != user_id:
            raise SlotUnavailableError("Это не ваша запись.")
        if appointment.status not in (AppointmentStatus.pending, AppointmentStatus.confirmed):
            raise SlotUnavailableError("Эту запись уже нельзя отменить.")

        appointment_dt = settings.now_local().replace(
            hour=appointment.start_time.hour,
            minute=appointment.start_time.minute,
            second=appointment.start_time.second,
            microsecond=appointment.start_time.microsecond,
        )
        appointment_dt = appointment_dt.replace(
            year=appointment.appointment_date.year,
            month=appointment.appointment_date.month,
            day=appointment.appointment_date.day,
        )
        if user_id is not None:
            min_before = timedelta(hours=settings.cancel_min_hours_before)
            if appointment_dt - settings.now_local() < min_before:
                raise CancellationNotAllowedError(
                    f"Отменить запись можно не позднее чем за {settings.cancel_min_hours_before} ч. до начала."
                )

        await self.appointment_repo.cancel(appointment)
        await self.session.commit()
        return appointment
