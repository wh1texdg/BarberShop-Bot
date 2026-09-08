import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.handlers import admin, booking, start
from app.bot.middlewares.db import DbSessionMiddleware
from app.config import settings
from app.services.reminder_jobs import send_2h_reminders, send_day_before_reminders

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())

    # Admin router first so admin-only commands/buttons aren't swallowed by client handlers.
    dp.include_router(admin.router)
    dp.include_router(booking.router)
    dp.include_router(start.router)

    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(send_day_before_reminders, "cron", hour=10, minute=0, args=[bot])
    scheduler.add_job(send_2h_reminders, "interval", minutes=5, args=[bot])
    scheduler.start()

    logger.info("Bot starting")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
