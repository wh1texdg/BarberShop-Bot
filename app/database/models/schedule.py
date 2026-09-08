from time import time as _time
from datetime import time

from sqlalchemy import ForeignKey, Integer, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base


class Schedule(Base):
    """Weekly recurring working hours for a master. weekday: 0=Mon .. 6=Sun."""

    __tablename__ = "schedules"
    __table_args__ = (UniqueConstraint("master_id", "weekday", name="uq_master_weekday"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-6, Mon-Sun
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)  # None => day off
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    break_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    break_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    master: Mapped["Master"] = relationship(back_populates="schedules")
