import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters.admin import IsAdmin
from app.bot.keyboards.menu import ADMIN_MENU, MAIN_MENU
from app.bot.states.booking_states import AdminClientStates, AdminMasterStates, AdminServiceStates
from app.config import settings
from app.database.models import AppointmentStatus, ExceptionType
from app.database.repositories.appointment_repo import AppointmentRepository
from app.database.repositories.catalog_repo import MasterRepository, ServiceRepository
from app.database.repositories.review_repo import ReviewRepository
from app.database.repositories.schedule_repo import ScheduleRepository
from app.database.repositories.user_repo import UserRepository
from app.services.booking_service import BookingService, SlotUnavailableError
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
STATUS_NAMES = {
    AppointmentStatus.pending: "ожидает",
    AppointmentStatus.confirmed: "подтверждена",
    AppointmentStatus.completed: "завершена",
    AppointmentStatus.cancelled: "отменена",
    AppointmentStatus.no_show: "не пришёл",
}


def appointment_actions(appointment_id: int, include_cancel: bool = True):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Завершено", callback_data=f"status:{appointment_id}:completed")
    builder.button(text="🚫 Не пришёл", callback_data=f"status:{appointment_id}:no_show")
    if include_cancel:
        builder.button(text="❌ Отменить", callback_data=f"admin_cancel:{appointment_id}")
    builder.adjust(2, 1)
    return builder.as_markup()


@router.message(Command("admin"))
async def admin_entry(message: Message) -> None:
    await message.answer("Админ-панель.", reply_markup=ADMIN_MENU)


@router.message(F.text == "Выйти из админки")
async def admin_exit(message: Message) -> None:
    await message.answer("Вы вышли из админ-панели.", reply_markup=MAIN_MENU)


@router.message(F.text == "Сегодня")
async def today_schedule(message: Message, session: AsyncSession) -> None:
    today = settings.now_local().date()
    appointments = await AppointmentRepository(session).list_all_for_date(today)
    if not appointments:
        await message.answer(f"{today:%d.%m.%Y}\n\nЗаписей на сегодня нет.")
        return

    await message.answer(f"Расписание на сегодня — {today:%d.%m.%Y}")
    for appointment in appointments:
        client = appointment.user.name or appointment.user.username or str(appointment.user.telegram_id)
        status = STATUS_NAMES[appointment.status]
        text = (
            f"{appointment.start_time:%H:%M}–{appointment.end_time:%H:%M}\n"
            f"{client}\n{appointment.service.name}, мастер {appointment.master.name}\n"
            f"Статус: {status}\nТелефон: {appointment.user.phone or '-'}"
        )
        markup = appointment_actions(appointment.id) if appointment.status in (AppointmentStatus.pending, AppointmentStatus.confirmed) else None
        await message.answer(text, reply_markup=markup)


@router.message(F.text == "Записи")
async def upcoming_bookings(message: Message, session: AsyncSession) -> None:
    today = settings.now_local().date()
    appointments = await AppointmentRepository(session).list_future_active(today, 14)
    if not appointments:
        await message.answer("Предстоящих записей на ближайшие 14 дней нет.")
        return

    current_date = None
    for appointment in appointments:
        if appointment.appointment_date != current_date:
            current_date = appointment.appointment_date
            await message.answer(f"— {current_date:%d.%m.%Y} —")
        client = appointment.user.name or appointment.user.username or str(appointment.user.telegram_id)
        text = (
            f"{appointment.start_time:%H:%M} — {client}\n"
            f"{appointment.service.name}, мастер {appointment.master.name}\n"
            f"Телефон: {appointment.user.phone or '-'}"
        )
        await message.answer(text, reply_markup=appointment_actions(appointment.id))


@router.callback_query(F.data.startswith("admin_cancel:"))
async def admin_cancel_appointment(callback: CallbackQuery, session: AsyncSession) -> None:
    appointment_id = int(callback.data.split(":", 1)[1])
    try:
        appointment = await BookingService(session).cancel_appointment(appointment_id, user_id=None)
    except SlotUnavailableError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await NotificationService(callback.bot).booking_cancelled(appointment.user)
    await callback.message.edit_text("Запись отменена, клиент уведомлён.")
    await callback.answer()


@router.callback_query(F.data.startswith("status:"))
async def change_appointment_status(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in {"completed", "no_show"}:
        await callback.answer("Некорректный статус.", show_alert=True)
        return

    appointment = await AppointmentRepository(session).get(int(parts[1]))
    if appointment is None:
        await callback.answer("Запись не найдена.", show_alert=True)
        return
    if appointment.status not in (AppointmentStatus.pending, AppointmentStatus.confirmed):
        await callback.answer("Статус уже нельзя изменить.", show_alert=True)
        return

    status = AppointmentStatus(parts[2])
    now = settings.now_local()
    start_dt = datetime.combine(appointment.appointment_date, appointment.start_time, tzinfo=settings.tzinfo)
    end_dt = datetime.combine(appointment.appointment_date, appointment.end_time, tzinfo=settings.tzinfo)
    if status == AppointmentStatus.completed and now < end_dt:
        await callback.answer("Завершить визит можно после времени окончания.", show_alert=True)
        return
    if status == AppointmentStatus.no_show and now < start_dt:
        await callback.answer("Неявку можно отметить только после начала визита.", show_alert=True)
        return
    await AppointmentRepository(session).set_status(appointment, status)
    await session.commit()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"Запись #{appointment.id}: статус «{STATUS_NAMES[status]}».")
    if status == AppointmentStatus.completed:
        await NotificationService(callback.bot).review_request(appointment.user, appointment)
    await callback.answer()


@router.message(F.text == "Мастера")
async def list_masters(message: Message, session: AsyncSession) -> None:
    masters = await MasterRepository(session).list_active()
    if not masters:
        await message.answer("Мастеров пока нет.")
        return
    lines = ["Мастера:"]
    for master in masters:
        services = ", ".join(ms.service.name for ms in master.services if ms.service and ms.service.is_active) or "услуги не назначены"
        lines.append(f"\n• {master.name} (id={master.id})\n  {master.description or 'Без описания'}\n  Услуги: {services}")
    lines.append("\nДобавить: /add_master\nДеактивировать: /remove_master <id>\nНазначить услугу: /assign_service <master_id> <service_id>")
    await message.answer("\n".join(lines))


@router.message(Command("add_master"))
async def add_master_start(message: Message, state: FSMContext) -> None:
    await message.answer("Введите имя нового мастера:")
    await state.set_state(AdminMasterStates.entering_name)


@router.message(AdminMasterStates.entering_name)
async def add_master_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 128:
        await message.answer("Введите корректное имя.")
        return
    await state.update_data(name=name)
    await message.answer("Введите описание или «-»:")
    await state.set_state(AdminMasterStates.entering_description)


@router.message(AdminMasterStates.entering_description)
async def add_master_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    description = (message.text or "").strip()
    if description == "-":
        description = None
    data = await state.get_data()
    master = await MasterRepository(session).create(data["name"], description)
    await session.commit()
    await message.answer(f"Мастер «{master.name}» добавлен (id={master.id}).")
    await state.clear()


@router.message(Command("remove_master"))
async def remove_master(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используйте: /remove_master <id>")
        return
    if not await MasterRepository(session).deactivate(int(parts[1])):
        await message.answer("Мастер не найден.")
        return
    await session.commit()
    await message.answer("Мастер деактивирован.")


@router.message(Command("assign_service"))
async def assign_service(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Используйте: /assign_service <master_id> <service_id>")
        return
    if not await MasterRepository(session).assign_service(int(parts[1]), int(parts[2])):
        await message.answer("Проверьте ID мастера и услуги: они должны существовать и быть активными.")
        return
    await session.commit()
    await message.answer("Услуга назначена мастеру.")


@router.message(F.text == "Услуги (админ)")
async def list_services_admin(message: Message, session: AsyncSession) -> None:
    services = await ServiceRepository(session).list_active()
    if not services:
        await message.answer("Услуг пока нет.")
        return
    lines = ["Услуги:"]
    for service in services:
        lines.append(f"• {service.name} — {service.price} ₽, {service.duration_minutes} мин (id={service.id})")
    lines.append("\nДобавить: /add_service\nИзменить цену: /set_price <id> <цена>\nДеактивировать: /remove_service <id>")
    await message.answer("\n".join(lines))


@router.message(Command("add_service"))
async def add_service_start(message: Message, state: FSMContext) -> None:
    await message.answer("Введите название услуги:")
    await state.set_state(AdminServiceStates.entering_name)


@router.message(AdminServiceStates.entering_name)
async def add_service_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 128:
        await message.answer("Введите корректное название.")
        return
    await state.update_data(name=name)
    await message.answer("Введите стоимость в рублях:")
    await state.set_state(AdminServiceStates.entering_price)


@router.message(AdminServiceStates.entering_price)
async def add_service_price(message: Message, state: FSMContext) -> None:
    try:
        price = Decimal((message.text or "").replace(",", "."))
    except InvalidOperation:
        await message.answer("Цена должна быть числом.")
        return
    if not price.is_finite() or price < 0 or price > Decimal("9999999.99"):
        await message.answer("Цена должна быть от 0 до 9 999 999,99 ₽.")
        return
    await state.update_data(price=str(price))
    await message.answer("Введите длительность в минутах:")
    await state.set_state(AdminServiceStates.entering_duration)


@router.message(AdminServiceStates.entering_duration)
async def add_service_duration(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value.isdigit() or not 5 <= int(value) <= 1440:
        await message.answer("Введите длительность от 5 до 1440 минут.")
        return
    await state.update_data(duration_minutes=int(value))
    await message.answer("Введите описание или «-»:")
    await state.set_state(AdminServiceStates.entering_description)


@router.message(AdminServiceStates.entering_description)
async def add_service_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    description = (message.text or "").strip()
    if description == "-":
        description = None
    data = await state.get_data()
    service = await ServiceRepository(session).create(data["name"], Decimal(data["price"]), data["duration_minutes"], description)
    await session.commit()
    await message.answer(f"Услуга «{service.name}» добавлена (id={service.id}).")
    await state.clear()


@router.message(Command("set_price"))
async def set_price(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer("Используйте: /set_price <id> <цена>")
        return
    try:
        price = Decimal(parts[2].replace(",", "."))
    except InvalidOperation:
        await message.answer("Цена должна быть числом.")
        return
    if not price.is_finite() or price < 0:
        await message.answer("Цена должна быть конечным неотрицательным числом.")
        return
    if not await ServiceRepository(session).update_price(int(parts[1]), price):
        await message.answer("Услуга не найдена.")
        return
    await session.commit()
    await message.answer("Цена обновлена.")


@router.message(Command("remove_service"))
async def remove_service(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используйте: /remove_service <id>")
        return
    if not await ServiceRepository(session).deactivate(int(parts[1])):
        await message.answer("Услуга не найдена.")
        return
    await session.commit()
    await message.answer("Услуга деактивирована.")


@router.message(F.text == "Расписание")
async def schedule_overview(message: Message, session: AsyncSession) -> None:
    masters = await MasterRepository(session).list_active()
    if not masters:
        await message.answer("Активных мастеров нет.")
        return
    schedule_repo = ScheduleRepository(session)
    parts = []
    for master in masters:
        schedules = {item.weekday: item for item in await schedule_repo.get_all_for_master(master.id)}
        lines = [f"{master.name} (id={master.id})"]
        for weekday in range(7):
            schedule = schedules.get(weekday)
            if not schedule or schedule.start_time is None or schedule.end_time is None:
                value = "выходной"
            else:
                value = f"{schedule.start_time:%H:%M}–{schedule.end_time:%H:%M}"
                if schedule.break_start and schedule.break_end:
                    value += f", перерыв {schedule.break_start:%H:%M}–{schedule.break_end:%H:%M}"
            lines.append(f"{WEEKDAY_NAMES[weekday]}: {value}")
        parts.append("\n".join(lines))
    parts.append(
        "Команды:\n/set_schedule <master_id> <день 0-6> <HH:MM> <HH:MM> [перерыв_с] [перерыв_до]\n"
        "/set_dayoff <master_id> <день 0-6>\n/add_exception <master_id> <YYYY-MM-DD> dayoff\n"
        "/add_exception <master_id> <YYYY-MM-DD> <HH:MM> <HH:MM>"
    )
    await message.answer("\n\n".join(parts))


@router.message(Command("set_schedule"))
async def set_schedule(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) not in (5, 7) or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Используйте: /set_schedule <master_id> <день 0-6> <HH:MM> <HH:MM> [перерыв_с] [перерыв_до]")
        return
    try:
        master_id, weekday = int(parts[1]), int(parts[2])
        if not 0 <= weekday <= 6:
            raise ValueError
        start_time = datetime.strptime(parts[3], "%H:%M").time()
        end_time = datetime.strptime(parts[4], "%H:%M").time()
        break_start = datetime.strptime(parts[5], "%H:%M").time() if len(parts) == 7 else None
        break_end = datetime.strptime(parts[6], "%H:%M").time() if len(parts) == 7 else None
    except ValueError:
        await message.answer("Проверьте формат дня и времени.")
        return
    if start_time >= end_time:
        await message.answer("Начало рабочего дня должно быть раньше конца.")
        return
    if break_start is not None and (break_end is None or break_start >= break_end or break_start < start_time or break_end > end_time):
        await message.answer("Перерыв должен находиться внутри рабочего дня и иметь корректные границы.")
        return
    master = await MasterRepository(session).get(master_id)
    if master is None or not master.is_active:
        await message.answer("Активный мастер с таким ID не найден.")
        return
    await ScheduleRepository(session).upsert_weekday(master_id, weekday, start_time, end_time, break_start, break_end)
    await session.commit()
    await message.answer(f"Расписание {master.name} на {WEEKDAY_NAMES[weekday]} обновлено.")


@router.message(Command("set_dayoff"))
async def set_dayoff(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit() or not 0 <= int(parts[2]) <= 6:
        await message.answer("Используйте: /set_dayoff <master_id> <день 0-6>")
        return
    master_id, weekday = int(parts[1]), int(parts[2])
    if await MasterRepository(session).get(master_id) is None:
        await message.answer("Мастер не найден.")
        return
    await ScheduleRepository(session).upsert_weekday(master_id, weekday, None, None, None, None)
    await session.commit()
    await message.answer(f"{WEEKDAY_NAMES[weekday]} теперь выходной.")


@router.message(Command("add_exception"))
async def add_exception(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) not in (4, 5) or not parts[1].isdigit():
        await message.answer("Используйте /add_exception <master_id> <YYYY-MM-DD> dayoff или <HH:MM> <HH:MM>")
        return
    try:
        master_id = int(parts[1])
        on_date = datetime.strptime(parts[2], "%Y-%m-%d").date()
    except ValueError:
        await message.answer("Дата должна быть в формате YYYY-MM-DD.")
        return
    if await MasterRepository(session).get(master_id) is None:
        await message.answer("Мастер не найден.")
        return

    if len(parts) == 4 and parts[3].lower() == "dayoff":
        await ScheduleRepository(session).add_exception(master_id, on_date, ExceptionType.day_off)
        await session.commit()
        await message.answer(f"{on_date:%d.%m.%Y}: выходной установлен.")
        return

    if len(parts) == 5:
        try:
            start_time = datetime.strptime(parts[3], "%H:%M").time()
            end_time = datetime.strptime(parts[4], "%H:%M").time()
        except ValueError:
            await message.answer("Время должно быть HH:MM.")
            return
        if start_time >= end_time:
            await message.answer("Начало должно быть раньше конца.")
            return
        await ScheduleRepository(session).add_exception(master_id, on_date, ExceptionType.custom_hours, start_time, end_time)
        await session.commit()
        await message.answer(f"{on_date:%d.%m.%Y}: часы {parts[3]}–{parts[4]} установлены.")
        return
    await message.answer("Не удалось распознать команду.")


@router.message(F.text == "Клиенты")
async def clients_start(message: Message, state: FSMContext) -> None:
    await message.answer("Введите имя, username или телефон для поиска:")
    await state.set_state(AdminClientStates.searching)


@router.message(AdminClientStates.searching)
async def clients_search(message: Message, state: FSMContext, session: AsyncSession) -> None:
    query = (message.text or "").strip()
    if not query:
        await message.answer("Введите поисковый запрос.")
        return
    users = await UserRepository(session).search(query)
    if not users:
        await message.answer("Клиенты не найдены.")
    else:
        lines = [f"Найдено: {len(users)}"]
        for user in users[:20]:
            lines.append(f"\n#{user.id} — {user.name or 'без имени'} (@{user.username or '-'})\nТелефон: {user.phone or '-'}\nTelegram ID: {user.telegram_id}")
        await message.answer("\n".join(lines))
    await state.clear()


@router.message(F.text == "Статистика")
async def statistics(message: Message, session: AsyncSession) -> None:
    end = settings.now_local().date() + timedelta(days=1)
    start = end - timedelta(days=30)
    data = await AppointmentRepository(session).stats(start, end)
    statuses = data["statuses"]
    completed = statuses.get(AppointmentStatus.completed, 0)
    cancelled = statuses.get(AppointmentStatus.cancelled, 0)
    confirmed = statuses.get(AppointmentStatus.confirmed, 0)
    revenue = data["revenue"]
    lines = [
        "Статистика за последние 30 дней:",
        f"Всего записей: {sum(statuses.values())}",
        f"Завершено: {completed}",
        f"Предстоящих/подтверждённых: {confirmed}",
        f"Отменено: {cancelled}",
        f"Выручка по завершённым: {Decimal(revenue):.2f} ₽",
        "",
        "Популярные услуги:",
    ]
    if data["popular"]:
        lines.extend(f"• {name} — {count}" for name, count in data["popular"][:5])
    else:
        lines.append("Пока нет завершённых визитов.")
    await message.answer("\n".join(lines))


@router.message(F.text == "Отзывы")
async def reviews(message: Message, session: AsyncSession) -> None:
    reviews = await ReviewRepository(session).list_recent(15)
    if not reviews:
        await message.answer("Отзывов пока нет.")
        return
    lines = ["Последние отзывы:"]
    for review in reviews:
        client = review.appointment.user.name or review.appointment.user.username or str(review.appointment.user.telegram_id)
        comment = review.comment or "без комментария"
        lines.append(f"\n{client} — {'⭐' * review.rating}\n{comment}\n{review.appointment.service.name}, {review.appointment.master.name}")
    await message.answer("\n".join(lines))
