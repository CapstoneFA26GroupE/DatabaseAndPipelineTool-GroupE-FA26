from datetime import datetime

from sqlalchemy import BigInteger, Index, Integer, DateTime, String, func, ForeignKeyConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.enums import CameraType, camera_type_enum

# this tell camera type, like front regular, front wide or driver


class Frame(Base):
    __tablename__ = "frames"
# this foregin key constantraint is used to link frame to segment, 
# when segment is deleted, all frames belong to this segment will be deleted too
    __table_args__ = (
        ForeignKeyConstraint(
            ["route_id", "segment_id"],
            ["segments.route_id", "segments.segment_id"],
            ondelete="CASCADE",
        ),
        # this index makes "frames of this route with this intersection label" lookups fast
        Index("ix_frames_route_intersection_type", "route_id", "intersection_type"),
    )

    frame_pk: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )
    route_id: Mapped[str] = mapped_column(
        nullable=False,
    )
    segment_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    frame_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    camera: Mapped[CameraType] = mapped_column(
        camera_type_enum,
        nullable=False,
    )
    log_mono_time: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    openpilot_features: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    width_px: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    height_px: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # intersection label set by the intersection_worker after upload:
    # signalized_intersection, unsignalized_intersection, non_intersection or unknown (no gps)
    intersection_type: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    # why the frame got its label: nearest intersection, distance, map/camera evidence, confidence
    intersection_details: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    def __repr__(self):
        return f"Frame({self.frame_pk}, {self.route_id}, {self.segment_id}, {self.frame_id})"
