import logging
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select

from app.config import settings
from app.database.models import Appointment, AppointmentStatus
from app.database.session import async_session_factory
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


async def send_day_before_reminders(bot: Bot) -> None:
    target_date = settings.now_local().date() + timedelta(days=1)
    async with async_session_factory() as session:
        result = await session.execute(
            select(Appointment)
            .where(
                Appointment.appointment_date == target_date,
                Appointment.status == AppointmentStatus.confirmed,
                Appointment.day_before_reminded.is_(False),
            )
            .with_for_update()
        )
        appointments = result.scalars().all()
        service = NotificationService(bot)
        sent = 0
        for appointment in appointments:
            await session.refresh(appointment, attribute_names=["user", "master", "service"])
            if await service.reminder_day_before(appointment.user, appointment, appointment.service, appointment.master):
                appointment.day_before_reminded = True
                sent += 1
        await session.commit()
        logger.info("Sent %d day-before reminders for %s", sent, target_date)


async def send_2h_reminders(bot: Bot) -> None:
    now = settings.now_local()
    target_minute = now + timedelta(hours=2)
    window_start = target_minute - timedelta(minutes=5)
    window_end = target_minute + timedelta(minutes=5)
    async with async_session_factory() as session:
        result = await session.execute(
            select(Appointment)
            .where(
                Appointment.appointment_date == target_minute.date(),
                Appointment.status == AppointmentStatus.confirmed,
                Appointment.two_hour_reminded.is_(False),
            )
            .with_for_update()
        )
        candidates = result.scalars().all()
        service = NotificationService(bot)
        sent = 0
        for appointment in candidates:
            start_dt = datetime.combine(appointment.appointment_date, appointment.start_time, tzinfo=settings.tzinfo)
            if window_start <= start_dt < window_end:
                await session.refresh(appointment, attribute_names=["user"])
                if await service.reminder_2h(appointment.user, appointment):
                    appointment.two_hour_reminded = True
                    sent += 1
        await session.commit()
        logger.info("Sent %d two-hour reminders", sent)
