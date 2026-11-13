from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.enums import DatasetExportStatus, dataset_export_status_enum


class DatasetExport(Base):
    __tablename__ = "dataset_exports"

    export_id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )
    route_id: Mapped[str] = mapped_column(
        ForeignKey("routes.route_id", ondelete="CASCADE"),
        nullable=False,
    )
    camera_views: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )
    status: Mapped[DatasetExportStatus] = mapped_column(
        dataset_export_status_enum,
        nullable=False,
    )
    zip_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.artifact_id"),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    # when set, only frames with these intersection labels are exported (None exports every frame)
    intersection_types: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self):
        return f"DatasetExport({self.export_id}, {self.route_id}, {self.status})"
