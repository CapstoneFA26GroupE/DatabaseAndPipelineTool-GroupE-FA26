from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.enums import DatasetExportStatus
from db.models.dataset_export import DatasetExport


class DatasetExportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, export_id: int) -> DatasetExport | None:
        return await self._session.get(DatasetExport, export_id)

    async def get_by_route_id(self, route_id: str) -> list[DatasetExport]:
        stmt = (
            select(DatasetExport)
            .where(DatasetExport.route_id == route_id)
            .order_by(DatasetExport.queued_at.desc())
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def list_all(self) -> list[DatasetExport]:
        stmt = select(DatasetExport).order_by(DatasetExport.queued_at.desc())
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_by_status(self, status: DatasetExportStatus) -> list[DatasetExport]:
        stmt = (
            select(DatasetExport)
            .where(DatasetExport.status == status)
            .order_by(DatasetExport.queued_at.asc())
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_next_by_status(self, status: DatasetExportStatus) -> DatasetExport | None:
        stmt = (
            select(DatasetExport)
            .where(DatasetExport.status == status)
            .order_by(DatasetExport.queued_at.asc())
            .limit(1)
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def create(
        self,
        route_id: str,
        camera_views: list[str],
        status: DatasetExportStatus,
        intersection_types: list[str] | None = None,
    ) -> DatasetExport:
        dataset_export = DatasetExport(
            route_id=route_id,
            camera_views=camera_views,
            status=status,
            intersection_types=intersection_types,
        )
        self._session.add(dataset_export)
        await self._session.flush()
        return dataset_export

    async def save(self, dataset_export: DatasetExport) -> DatasetExport:
        self._session.add(dataset_export)
        await self._session.flush()
        return dataset_export

    async def delete(self, dataset_export: DatasetExport) -> None:
        await self._session.delete(dataset_export)
        await self._session.flush()
