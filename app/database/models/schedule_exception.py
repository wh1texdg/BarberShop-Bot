import enum
from datetime import date, time

from sqlalchemy import ForeignKey, Date, Time, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base


class ExceptionType(str, enum.Enum):
    day_off = "day_off"          # master doesn't work this date at all
    custom_hours = "custom_hours"  # master works this date with different hours


class ScheduleException(Base):
    __tablename__ = "schedule_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    type: Mapped[ExceptionType] = mapped_column(Enum(ExceptionType), nullable=False)

    master: Mapped["Master"] = relationship(back_populates="exceptions")
