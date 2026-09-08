import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ADMIN_IDS", "")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database.models import Base


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # SQLite doesn't support SELECT ... FOR UPDATE, so appointment_repo's
    # locking read is skipped there — fine for unit-testing the slot math
    # and overlap logic in isolation; the locking itself only matters against
    # concurrent transactions, which these tests don't exercise.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s

    await engine.dispose()
