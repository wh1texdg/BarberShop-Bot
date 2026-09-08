from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Записаться")],
        [KeyboardButton(text="Мои записи"), KeyboardButton(text="Услуги")],
        [KeyboardButton(text="О барбершопе"), KeyboardButton(text="Помощь")],
    ],
    resize_keyboard=True,
)

ADMIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Сегодня"), KeyboardButton(text="Записи")],
        [KeyboardButton(text="Мастера"), KeyboardButton(text="Услуги (админ)")],
        [KeyboardButton(text="Расписание"), KeyboardButton(text="Клиенты")],
        [KeyboardButton(text="Статистика"), KeyboardButton(text="Отзывы")],
        [KeyboardButton(text="Выйти из админки")],
    ],
    resize_keyboard=True,
)
