import logging
from datetime import date as date_cls, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.booking import (
    cancel_confirm_kb,
    confirm_kb,
    dates_kb,
    masters_kb,
    history_kb,
    review_kb,
    services_kb,
    times_kb,
)
from app.bot.keyboards.menu import MAIN_MENU
from app.bot.states.booking_states import BookingStates, ReviewStates
from app.config import settings
from app.database.models import AppointmentStatus, Review
from app.database.repositories.appointment_repo import AppointmentRepository
from app.database.repositories.catalog_repo import MasterRepository, ServiceRepository
from app.database.repositories.user_repo import UserRepository
from app.database.repositories.review_repo import ReviewRepository
from app.services.booking_service import BookingService, CancellationNotAllowedError, SlotUnavailableError
from app.services.notification_service import NotificationService
from app.services.schedule_service import ScheduleService

logger = logging.getLogger(__name__)
router = Router(name="booking")


@router.message(F.text == "Записаться")
async def start_booking(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    services = await ServiceRepository(session).list_active()
    if not services:
        await message.answer("Пока нет доступных услуг. Загляните позже.")
        return
    await state.set_state(BookingStates.choosing_service)
    await message.answer("Выберите услугу:", reply_markup=services_kb(services))


@router.callback_query(BookingStates.choosing_service, F.data.startswith("svc:"))
async def choose_service(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    service_id = int(callback.data.split(":")[1])
    service = await ServiceRepository(session).get(service_id)
    if service is None or not service.is_active:
        await callback.answer("Эта услуга больше недоступна.", show_alert=True)
        return

    masters = await MasterRepository(session).list_for_service(service_id)
    text = f"{service.name}\n\nСтоимость: {service.price} ₽\nПродолжительность: {service.duration_minutes} минут."
    if not masters:
        await callback.message.edit_text(text + "\n\nСейчас для этой услуги нет доступных мастеров.")
        await state.clear()
        await callback.answer()
        return

    await state.update_data(service_id=service.id)
    await callback.message.edit_text(text)
    await callback.message.answer("Выберите мастера:", reply_markup=masters_kb(masters))
    await state.set_state(BookingStates.choosing_master)
    await callback.answer()


@router.callback_query(BookingStates.choosing_master, F.data.startswith("master:"))
async def choose_master(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    raw = callback.data.split(":", 1)[1]
    data = await state.get_data()
    service_id = data["service_id"]

    if raw == "any":
        await state.update_data(any_master=True, master_id=None, master_name="Любой мастер")
        display_name = "Любой мастер"
    else:
        master = await MasterRepository(session).get(int(raw))
        if master is None or not master.is_active or not await MasterRepository(session).has_service(master.id, service_id):
            await callback.answer("Этот мастер не может выполнить выбранную услугу.", show_alert=True)
            return
        await state.update_data(any_master=False, master_id=master.id, master_name=master.name)
        display_name = master.name

    await callback.message.edit_text(f"Мастер: {display_name}")
    await callback.message.answer("Выберите дату:", reply_markup=dates_kb())
    await state.set_state(BookingStates.choosing_date)
    await callback.answer()


@router.callback_query(BookingStates.choosing_date, F.data.startswith("date:"))
async def choose_date(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    try:
        chosen_date = date_cls.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректная дата.", show_alert=True)
        return

    today = settings.now_local().date()
    if chosen_date < today:
        await callback.answer("Нельзя выбрать прошедшую дату.", show_alert=True)
        return

    data = await state.get_data()
    service = await ServiceRepository(session).get(data["service_id"])
    if service is None or not service.is_active:
        await callback.answer("Услуга больше недоступна.", show_alert=True)
        await state.clear()
        return

    master_repo = MasterRepository(session)
    if data.get("any_master"):
        masters = await master_repo.list_for_service(service.id)
        selected_master = None
        slots = []
        for candidate in masters:
            candidate_slots = await ScheduleService(session).get_available_slots(candidate.id, chosen_date, service.duration_minutes)
            if candidate_slots:
                selected_master, slots = candidate, candidate_slots
                break
        if selected_master is None:
            await callback.answer("На эту дату нет свободного времени ни у одного мастера.", show_alert=True)
            return
        await state.update_data(master_id=selected_master.id, master_name=selected_master.name)
    else:
        if data.get("master_id") is None:
            await callback.answer("Сначала выберите мастера.", show_alert=True)
            return
        slots = await ScheduleService(session).get_available_slots(
            data["master_id"], chosen_date, service.duration_minutes
        )

    if not slots:
        await callback.answer("На эту дату нет свободного времени. Выберите другую дату.", show_alert=True)
        return

    await state.update_data(date=chosen_date.isoformat())
    current_data = await state.get_data()
    await callback.message.edit_text(
        f"Дата: {chosen_date.strftime('%d.%m.%Y')}\nМастер: {await _master_name(session, current_data['master_id'])}"
    )
    await callback.message.answer(
        f"Свободно на {chosen_date.strftime('%d.%m.%Y')}:\nВыберите время:",
        reply_markup=times_kb([t.strftime("%H:%M") for t in slots]),
    )
    await state.set_state(BookingStates.choosing_time)
    await callback.answer()


@router.callback_query(BookingStates.choosing_time, F.data.startswith("time:"))
async def choose_time(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    time_str = callback.data.split(":", 1)[1]
    try:
        selected_time = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        await callback.answer("Некорректное время.", show_alert=True)
        return

    data = await state.get_data()
    service = await ServiceRepository(session).get(data["service_id"])
    if service is None or not service.is_active or not data.get("master_id"):
        await callback.answer("Запись устарела. Начните заново.", show_alert=True)
        await state.clear()
        return

    available = await ScheduleService(session).get_available_slots(
        data["master_id"], date_cls.fromisoformat(data["date"]), service.duration_minutes
    )
    if selected_time not in available:
        await callback.answer("Это время уже недоступно. Выберите другой слот.", show_alert=True)
        return

    await state.update_data(time=time_str)
    user = await UserRepository(session).get_or_create(callback.from_user.id, callback.from_user.username)
    await session.commit()
    await callback.message.edit_text(f"Время: {time_str}")

    if user.name and user.phone:
        await state.update_data(name=user.name, phone=user.phone)
        await show_confirmation(callback.message, state, session)
    else:
        await callback.message.answer("Как к вам обращаться? Введите имя:")
        await state.set_state(BookingStates.entering_name)
    await callback.answer()


@router.message(BookingStates.entering_name)
async def enter_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 128:
        await message.answer("Введите корректное имя.")
        return
    await state.update_data(name=name)
    await message.answer("Введите номер телефона (например, +79991234567):")
    await state.set_state(BookingStates.entering_phone)


@router.message(BookingStates.entering_phone)
async def enter_phone(message: Message, state: FSMContext, session: AsyncSession) -> None:
    phone = (message.text or "").strip()
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not 10 <= len(digits) <= 15:
        await message.answer("Похоже, номер введён некорректно. Попробуйте ещё раз.")
        return
    await state.update_data(phone=f"+{digits}")
    await show_confirmation(message, state, session)


async def show_confirmation(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    service = await ServiceRepository(session).get(data["service_id"])
    master = await MasterRepository(session).get(data["master_id"])
    if service is None or master is None or not service.is_active or not master.is_active:
        await message.answer("Что-то пошло не так, начните запись заново.", reply_markup=MAIN_MENU)
        await state.clear()
        return

    text = (
        "Проверьте запись\n\n"
        f"Услуга: {service.name}\n"
        f"Мастер: {master.name}\n"
        f"Дата: {date_cls.fromisoformat(data['date']).strftime('%d.%m.%Y')}\n"
        f"Время: {data['time']}\n"
        f"Стоимость: {service.price} ₽\n"
        f"Продолжительность: {service.duration_minutes} минут\n\n"
        f"Имя: {data['name']}\nТелефон: {data['phone']}"
    )
    await message.answer(text, reply_markup=confirm_kb())
    await state.set_state(BookingStates.confirming)


@router.callback_query(BookingStates.confirming, F.data == "confirm:restart")
async def restart_booking(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    services = await ServiceRepository(session).list_active()
    await callback.message.edit_text("Выберите услугу заново:")
    await callback.message.answer("Выберите услугу:", reply_markup=services_kb(services))
    await state.set_state(BookingStates.choosing_service)
    await callback.answer()


@router.callback_query(BookingStates.confirming, F.data == "confirm:cancel")
async def cancel_booking_flow(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Запись отменена.")
    await callback.message.answer("Главное меню:", reply_markup=MAIN_MENU)
    await callback.answer()


@router.callback_query(BookingStates.confirming, F.data == "confirm:yes")
async def confirm_booking(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    user = await UserRepository(session).get_or_create(callback.from_user.id, callback.from_user.username)
    await UserRepository(session).update_contact(user, data["name"], data["phone"])
    await session.commit()

    try:
        result = await BookingService(session).create_appointment(
            user_id=user.id,
            master_id=data["master_id"],
            service_id=data["service_id"],
            on_date=date_cls.fromisoformat(data["date"]),
            start_time=datetime.strptime(data["time"], "%H:%M").time(),
        )
    except SlotUnavailableError as exc:
        await session.rollback()
        await callback.message.edit_text(str(exc))
        await callback.message.answer("Попробуйте выбрать другое время.", reply_markup=MAIN_MENU)
        await state.clear()
        await callback.answer()
        return

    master = await MasterRepository(session).get(data["master_id"])
    notification_service = NotificationService(callback.bot)
    await notification_service.booking_created(user, result.appointment, result.service, master)
    await notification_service.notify_admins_new_booking(user, result.appointment, result.service, master)

    logger.info("Appointment %s created for user %s", result.appointment.id, user.telegram_id)
    await callback.message.edit_text("Вы успешно записаны! ✅")
    await callback.message.answer("Главное меню:", reply_markup=MAIN_MENU)
    await state.clear()
    await callback.answer()


@router.message(F.text == "Мои записи")
async def my_appointments(message: Message, session: AsyncSession) -> None:
    user = await UserRepository(session).get_or_create(message.from_user.id, message.from_user.username)
    await session.commit()
    appointments = await AppointmentRepository(session).list_upcoming_for_user(user.id, settings.now_local().date())
    if not appointments:
        await message.answer("У вас пока нет предстоящих записей.", reply_markup=history_kb())
        return
    for a in appointments:
        text = f"{a.appointment_date.strftime('%d.%m.%Y')}, {a.start_time.strftime('%H:%M')}\n{a.service.name}\nМастер {a.master.name}"
        await message.answer(text, reply_markup=cancel_confirm_kb(a.id))
    await message.answer("Также можно посмотреть завершённые и отменённые визиты:", reply_markup=history_kb())


@router.callback_query(F.data == "my_history")
async def my_history(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("История пока пуста.", show_alert=True)
        return
    appointments = await AppointmentRepository(session).list_history_for_user(user.id)
    if not appointments:
        await callback.message.answer("История визитов пока пуста.")
        await callback.answer()
        return

    for appointment in appointments[:20]:
        status = {
            AppointmentStatus.completed: "завершён",
            AppointmentStatus.cancelled: "отменён",
            AppointmentStatus.no_show: "неявка",
            AppointmentStatus.confirmed: "прошёл по времени",
        }.get(appointment.status, appointment.status.value)
        text = (
            f"{appointment.appointment_date:%d.%m.%Y}, {appointment.start_time:%H:%M}\n"
            f"{appointment.service.name}\nМастер {appointment.master.name}\n"
            f"Статус: {status}"
        )
        markup = review_kb(appointment.id) if appointment.status == AppointmentStatus.completed and appointment.review is None else None
        await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_yes:"))
async def cancel_yes(callback: CallbackQuery, session: AsyncSession) -> None:
    appointment_id = int(callback.data.split(":", 1)[1])
    user = await UserRepository(session).get_or_create(callback.from_user.id, callback.from_user.username)
    await session.commit()
    try:
        appointment = await BookingService(session).cancel_appointment(appointment_id, user_id=user.id)
    except (SlotUnavailableError, CancellationNotAllowedError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await NotificationService(callback.bot).booking_cancelled(user)
    await callback.message.edit_text("Запись отменена.")
    await callback.answer()


@router.callback_query(F.data == "cancel_no")
async def cancel_no(callback: CallbackQuery) -> None:
    await callback.answer("Хорошо, запись сохранена.")


@router.callback_query(F.data.startswith("review:"))
async def choose_review_rating(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await callback.answer("Некорректная оценка.", show_alert=True)
        return

    appointment_id, rating = int(parts[1]), int(parts[2])
    if not 1 <= rating <= 5:
        await callback.answer("Оценка должна быть от 1 до 5.", show_alert=True)
        return

    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    appointment = await AppointmentRepository(session).get(appointment_id)
    if user is None or appointment is None or appointment.user_id != user.id:
        await callback.answer("Этот отзыв нельзя оставить.", show_alert=True)
        return
    if appointment.status != AppointmentStatus.completed:
        await callback.answer("Оценить можно только завершённый визит.", show_alert=True)
        return
    if await ReviewRepository(session).get_by_appointment(appointment_id):
        await callback.answer("Вы уже оставили отзыв.", show_alert=True)
        return

    await state.update_data(appointment_id=appointment_id, rating=rating)
    await callback.message.edit_text("Спасибо! Напишите короткий комментарий или отправьте «-»:")
    await state.set_state(ReviewStates.entering_comment)
    await callback.answer()


@router.message(ReviewStates.entering_comment)
async def submit_review(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    appointment_id = data.get("appointment_id")
    rating = data.get("rating")
    if not appointment_id or not rating:
        await state.clear()
        await message.answer("Срок заполнения отзыва истёк.")
        return

    user = await UserRepository(session).get_by_telegram_id(message.from_user.id)
    appointment = await AppointmentRepository(session).get(appointment_id)
    if user is None or appointment is None or appointment.user_id != user.id:
        await state.clear()
        await message.answer("Не удалось найти визит для отзыва.")
        return
    if appointment.status != AppointmentStatus.completed:
        await state.clear()
        await message.answer("Оценить можно только завершённый визит.")
        return

    comment = (message.text or "").strip()
    if comment == "-":
        comment = None
    await ReviewRepository(session).create(appointment.id, appointment.user_id, rating, comment)
    await session.commit()
    await state.clear()
    await message.answer("Отзыв сохранён. Спасибо!")


async def _master_name(session: AsyncSession, master_id: int) -> str:
    master = await MasterRepository(session).get(master_id)
    return master.name if master else "-"
