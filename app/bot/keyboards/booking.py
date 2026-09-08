from datetime import timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.database.models import Master, Service


RUS_WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def services_kb(services: list[Service]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for service in services:
        builder.button(text=f"{service.name} — {service.price} ₽", callback_data=f"svc:{service.id}")
    builder.adjust(1)
    return builder.as_markup()


def masters_kb(masters: list[Master], include_any: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for master in masters:
        builder.button(text=master.name, callback_data=f"master:{master.id}")
    if include_any and len(masters) > 1:
        builder.button(text="Любой мастер", callback_data="master:any")
    builder.adjust(1)
    return builder.as_markup()


def dates_kb(days_ahead: int = 14) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    today = settings.now_local().date()
    for i in range(days_ahead):
        d = today + timedelta(days=i)
        label = f"{d.strftime('%d.%m')} ({RUS_WEEKDAYS[d.weekday()]})"
        builder.button(text=label, callback_data=f"date:{d.isoformat()}")
    builder.adjust(2)
    return builder.as_markup()


def times_kb(slots: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(text=slot, callback_data=f"time:{slot}")
    builder.adjust(4)
    return builder.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm:yes")
    builder.button(text="✏️ Изменить", callback_data="confirm:restart")
    builder.button(text="❌ Отменить", callback_data="confirm:cancel")
    builder.adjust(1)
    return builder.as_markup()


def cancel_confirm_kb(appointment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, отменить", callback_data=f"cancel_yes:{appointment_id}")
    builder.button(text="Нет", callback_data="cancel_no")
    builder.adjust(1)
    return builder.as_markup()


def review_kb(appointment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for rating in range(1, 6):
        builder.button(text="⭐" * rating, callback_data=f"review:{appointment_id}:{rating}")
    builder.adjust(1)
    return builder.as_markup()


def history_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 История визитов", callback_data="my_history")
    return builder.as_markup()
