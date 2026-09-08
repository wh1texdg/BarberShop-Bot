"""add historical appointment price

Revision ID: 0003_price_at_booking
Revises: 0002_reminder_flags
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_price_at_booking"
down_revision: Union[str, None] = "0002_reminder_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("appointments", sa.Column("price_at_booking", sa.Numeric(10, 2), nullable=True))
    op.execute(
        "UPDATE appointments SET price_at_booking = "
        "(SELECT price FROM services WHERE services.id = appointments.service_id)"
    )
    op.alter_column("appointments", "price_at_booking", nullable=False)


def downgrade() -> None:
    op.drop_column("appointments", "price_at_booking")
