import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.bot.keyboards.booking import review_kb
from app.config import settings
from app.database.models import Appointment, User

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def _safe_send(self, chat_id: int, text: str, **kwargs) -> bool:
        try:
            await self.bot.send_message(chat_id, text, **kwargs)
            return True
        except TelegramAPIError as exc:
            logger.warning("Failed to send notification to %s: %s", chat_id, exc)
            return False

    async def booking_created(self, user: User, appointment: Appointment, service, master) -> None:
        await self._safe_send(
            user.telegram_id,
            "Вы успешно записаны.\n\n"
            f"Услуга: {service.name}\n"
            f"Мастер: {master.name}\n"
            f"Дата: {appointment.appointment_date.strftime('%d.%m.%Y')}\n"
            f"Время: {appointment.start_time.strftime('%H:%M')}\n"
            f"Стоимость: {service.price} ₽",
        )

    async def booking_cancelled(self, user: User) -> None:
        await self._safe_send(user.telegram_id, "Ваша запись отменена.")

    async def reminder_day_before(self, user: User, appointment: Appointment, service, master) -> bool:
        return await self._safe_send(
            user.telegram_id,
            f"Напоминание: завтра в {appointment.start_time.strftime('%H:%M')} "
            f"у вас запись на «{service.name}» к мастеру {master.name}.",
        )

    async def reminder_2h(self, user: User, appointment: Appointment) -> bool:
        return await self._safe_send(
            user.telegram_id,
            f"Напоминание: через 2 часа у вас запись в {appointment.start_time.strftime('%H:%M')}.",
        )

    async def review_request(self, user: User, appointment: Appointment) -> bool:
        return await self._safe_send(
            user.telegram_id,
            "Спасибо за визит! Оцените обслуживание:",
            reply_markup=review_kb(appointment.id),
        )

    async def notify_admins_new_booking(self, user: User, appointment: Appointment, service, master) -> None:
        text = (
            "Новая запись\n\n"
            f"Клиент: {user.name or user.username or user.telegram_id}\n"
            f"Телефон: {user.phone or '-'}\n"
            f"Услуга: {service.name}\n"
            f"Мастер: {master.name}\n"
            f"Дата: {appointment.appointment_date.strftime('%d.%m.%Y')}\n"
            f"Время: {appointment.start_time.strftime('%H:%M')}"
        )
        for admin_id in settings.admin_ids_list:
            await self._safe_send(admin_id, text)
