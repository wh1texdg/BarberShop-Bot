from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Master, MasterService, Service


class MasterRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_active(self) -> list[Master]:
        result = await self.session.execute(
            select(Master)
            .where(Master.is_active.is_(True))
            .options(selectinload(Master.services).selectinload(MasterService.service))
            .order_by(Master.name)
        )
        return list(result.scalars().all())

    async def get(self, master_id: int) -> Master | None:
        result = await self.session.execute(
            select(Master).where(Master.id == master_id).options(
                selectinload(Master.services).selectinload(MasterService.service)
            )
        )
        return result.scalar_one_or_none()

    async def list_for_service(self, service_id: int) -> list[Master]:
        result = await self.session.execute(
            select(Master)
            .join(MasterService, MasterService.master_id == Master.id)
            .where(MasterService.service_id == service_id, Master.is_active.is_(True))
            .order_by(Master.name)
        )
        return list(result.scalars().all())

    async def has_service(self, master_id: int, service_id: int) -> bool:
        result = await self.session.execute(
            select(MasterService.id).where(
                MasterService.master_id == master_id,
                MasterService.service_id == service_id,
            )
        )
        return result.first() is not None

    async def create(self, name: str, description: str | None = None) -> Master:
        master = Master(name=name, description=description)
        self.session.add(master)
        await self.session.flush()
        return master

    async def deactivate(self, master_id: int) -> bool:
        master = await self.get(master_id)
        if master is None:
            return False
        master.is_active = False
        await self.session.flush()
        return True

    async def assign_service(self, master_id: int, service_id: int) -> bool:
        master = await self.get(master_id)
        service = await self.session.get(Service, service_id)
        if master is None or not master.is_active or service is None or not service.is_active:
            return False
        exists = await self.session.execute(
            select(MasterService).where(
                MasterService.master_id == master_id, MasterService.service_id == service_id
            )
        )
        if exists.scalar_one_or_none() is None:
            self.session.add(MasterService(master_id=master_id, service_id=service_id))
            await self.session.flush()
        return True


class ServiceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_active(self) -> list[Service]:
        result = await self.session.execute(
            select(Service).where(Service.is_active.is_(True)).order_by(Service.name)
        )
        return list(result.scalars().all())

    async def get(self, service_id: int) -> Service | None:
        result = await self.session.execute(select(Service).where(Service.id == service_id))
        return result.scalar_one_or_none()

    async def create(
        self, name: str, price, duration_minutes: int, description: str | None = None
    ) -> Service:
        service = Service(name=name, price=price, duration_minutes=duration_minutes, description=description)
        self.session.add(service)
        await self.session.flush()
        return service

    async def update_price(self, service_id: int, price) -> bool:
        service = await self.get(service_id)
        if service is None:
            return False
        service.price = price
        await self.session.flush()
        return True

    async def deactivate(self, service_id: int) -> bool:
        service = await self.get(service_id)
        if service is None:
            return False
        service.is_active = False
        await self.session.flush()
        return True
