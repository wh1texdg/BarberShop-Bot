import logging

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.menu import MAIN_MENU
from app.database.repositories.catalog_repo import ServiceRepository
from app.database.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

router = Router(name="start")

WELCOME_TEXT = "Добро пожаловать в барбершоп!\n\nВыберите действие в меню ниже."
HELP_TEXT = (
    "Как это работает:\n\n"
    "1. Нажмите «Записаться»\n"
    "2. Выберите услугу, мастера, дату и время\n"
    "3. Укажите имя и телефон\n"
    "4. Подтвердите запись\n\n"
    "Посмотреть или отменить запись можно в разделе «Мои записи»."
)
ABOUT_TEXT = "Барбершоп — стрижки, борода и уход. Актуальные услуги и свободное время доступны прямо в боте."


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    user_repo = UserRepository(session)
    await user_repo.get_or_create(message.from_user.id, message.from_user.username)
    await session.commit()
    logger.info("User %s started the bot", message.from_user.id)
    await message.answer(WELCOME_TEXT, reply_markup=MAIN_MENU)


@router.message(F.text == "Помощь")
async def show_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(F.text == "О барбершопе")
async def show_about(message: Message) -> None:
    await message.answer(ABOUT_TEXT)


@router.message(F.text == "Услуги")
async def show_services(message: Message, session: AsyncSession) -> None:
    service_repo = ServiceRepository(session)
    services = await service_repo.list_active()
    if not services:
        await message.answer("Пока нет доступных услуг.")
        return
    lines = ["Наши услуги:\n"]
    for s in services:
        lines.append(f"• {s.name} — {s.price} ₽ ({s.duration_minutes} мин)")
    await message.answer("\n".join(lines))
