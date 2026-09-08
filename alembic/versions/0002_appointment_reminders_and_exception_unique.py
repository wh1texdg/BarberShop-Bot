"""appointment reminder flags and unique schedule exceptions

Revision ID: 0002_reminder_flags
Revises: 0001_initial_schema
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_reminder_flags"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("day_before_reminded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "appointments",
        sa.Column("two_hour_reminded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_unique_constraint(
        "uq_schedule_exception_master_date", "schedule_exceptions", ["master_id", "date"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_schedule_exception_master_date", "schedule_exceptions", type_="unique")
    op.drop_column("appointments", "two_hour_reminded")
    op.drop_column("appointments", "day_before_reminded")
