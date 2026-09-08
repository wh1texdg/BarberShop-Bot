from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.repositories.user_repo import UserRepository


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, session: AsyncSession) -> bool:
        user_repo = UserRepository(session)
        return await user_repo.is_admin(event.from_user.id, settings.admin_ids_list)
