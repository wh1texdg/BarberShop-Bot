"""Optional helper to seed a couple of demo services/masters with a Mon-Fri
10:00-20:00 schedule, so the bot has something to show right after first run.

Usage (inside the bot container or a local venv with DATABASE_URL set):
    python -m scripts.seed
"""
import asyncio
from datetime import time

from app.database.repositories.catalog_repo import MasterRepository, ServiceRepository
from app.database.repositories.schedule_repo import ScheduleRepository
from app.database.session import async_session_factory


async def seed() -> None:
    async with async_session_factory() as session:
        service_repo = ServiceRepository(session)
        master_repo = MasterRepository(session)
        schedule_repo = ScheduleRepository(session)

        haircut = await service_repo.create("Мужская стрижка", price=1200, duration_minutes=60)
        beard = await service_repo.create("Стрижка бороды", price=700, duration_minutes=30)
        combo = await service_repo.create("Стрижка + борода", price=1700, duration_minutes=90)

        alexander = await master_repo.create("Александр", "Топ-мастер, 8 лет опыта")
        maxim = await master_repo.create("Максим", "Специалист по бородам")

        for master in (alexander, maxim):
            for service in (haircut, beard, combo):
                await master_repo.assign_service(master.id, service.id)
            for weekday in range(5):  # Mon-Fri
                await schedule_repo.upsert_weekday(
                    master.id, weekday, time(10, 0), time(20, 0), time(14, 0), time(15, 0)
                )

        await session.commit()
        print("Seeded: 3 services, 2 masters, Mon-Fri 10:00-20:00 schedule with a 14:00-15:00 break.")


if __name__ == "__main__":
    asyncio.run(seed())
