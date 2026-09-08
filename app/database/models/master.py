from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base


class Master(Base):
    __tablename__ = "masters"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    services: Mapped[list["MasterService"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    exceptions: Mapped[list["ScheduleException"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="master")
