from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Appointment, Review


class ReviewRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_appointment(self, appointment_id: int) -> Review | None:
        result = await self.session.execute(select(Review).where(Review.appointment_id == appointment_id))
        return result.scalar_one_or_none()

    async def create(self, appointment_id: int, user_id: int, rating: int, comment: str | None = None) -> Review:
        existing = await self.get_by_appointment(appointment_id)
        if existing is not None:
            return existing
        review = Review(appointment_id=appointment_id, user_id=user_id, rating=rating, comment=comment)
        self.session.add(review)
        await self.session.flush()
        return review

    async def list_recent(self, limit: int = 20) -> list[Review]:
        result = await self.session.execute(
            select(Review)
            .options(
                selectinload(Review.appointment).selectinload(Appointment.master),
                selectinload(Review.appointment).selectinload(Appointment.service),
                selectinload(Review.appointment).selectinload(Appointment.user),
            )
            .order_by(Review.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
