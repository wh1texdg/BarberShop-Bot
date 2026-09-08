import enum
from decimal import Decimal
from datetime import date, datetime, time

from sqlalchemy import ForeignKey, Date, Time, DateTime, Enum, func, Index, Boolean, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base


class AppointmentStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # Speeds up the availability/overlap check (master + date range scans).
        Index("ix_appointments_master_date", "master_id", "appointment_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    appointment_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus), default=AppointmentStatus.pending, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    day_before_reminded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    two_hour_reminded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    price_at_booking: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    user: Mapped["User"] = relationship(back_populates="appointments")
    master: Mapped["Master"] = relationship(back_populates="appointments")
    service: Mapped["Service"] = relationship(back_populates="appointments")
    review: Mapped["Review"] = relationship(back_populates="appointment", uselist=False)
