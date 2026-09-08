from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_or_create(self, telegram_id: int, username: str | None) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            if username and user.username != username:
                user.username = username
                await self.session.flush()
            return user
        user = User(telegram_id=telegram_id, username=username, role=UserRole.client)
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_contact(self, user: User, name: str, phone: str) -> None:
        user.name = name
        user.phone = phone
        await self.session.flush()

    async def search(self, query: str) -> list[User]:
        like = f"%{query}%"
        result = await self.session.execute(
            select(User).where(
                (User.name.ilike(like)) | (User.phone.ilike(like)) | (User.username.ilike(like))
            )
        )
        return list(result.scalars().all())

    async def is_admin(self, telegram_id: int, configured_admin_ids: list[int]) -> bool:
        if telegram_id in configured_admin_ids:
            return True
        user = await self.get_by_telegram_id(telegram_id)
        return bool(user and user.role == UserRole.admin)
