from dataclasses import dataclass
from typing import Any

from sqlalchemy import distinct, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.enums import CameraType
from db.models.frame import Frame


@dataclass(frozen=True)
class FrameRef:
    # the columns the intersection worker needs for one frame row (one row per camera)
    frame_pk: int
    segment_id: int
    frame_id: int
    camera: CameraType


class IntersectionRepository:
    # reads and writes the intersection labels stored on frames

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_frame_refs(self, route_id: str) -> list[FrameRef]:
        # this lists every frame row of a route (both cameras), oldest first
        stmt = (
            select(Frame.frame_pk, Frame.segment_id, Frame.frame_id, Frame.camera)
            .where(Frame.route_id == route_id)
            .order_by(Frame.segment_id, Frame.frame_id, Frame.camera)
        )
        result = await self._session.execute(stmt)
        return [FrameRef(*row) for row in result.all()]

    async def set_labels(self, rows: list[dict[str, Any]], chunk_size: int = 1000) -> None:
        # this writes labels by primary key: rows look like {"frame_pk", "intersection_type", "intersection_details"}
        for start in range(0, len(rows), chunk_size):
            await self._session.execute(update(Frame), rows[start:start + chunk_size])

    async def clear_labels(self, route_id: str) -> None:
        # this removes a route's labels so it can be labeled again
        await self._session.execute(
            update(Frame)
            .where(Frame.route_id == route_id)
            .values(intersection_type=None, intersection_details=None)
        )

    async def count_by_segment(self, route_id: str) -> dict[int, dict[str, int]]:
        # this counts labeled moments per segment and label (a moment is counted once even with two cameras)
        stmt = (
            select(Frame.segment_id, Frame.intersection_type, func.count(distinct(Frame.frame_id)))
            .where(Frame.route_id == route_id)
            .where(Frame.intersection_type.is_not(None))
            .group_by(Frame.segment_id, Frame.intersection_type)
        )
        counts: dict[int, dict[str, int]] = {}
        for segment_id, label, count in (await self._session.execute(stmt)).all():
            counts.setdefault(segment_id, {})[label] = int(count)
        return counts

    async def list_labeled_frames(
        self,
        route_id: str,
        segment_id: int | None = None,
        types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        # this lists labeled moments (one entry per segment/frame_id, not per camera), in order
        stmt = (
            select(Frame.segment_id, Frame.frame_id, Frame.intersection_type, Frame.intersection_details)
            .where(Frame.route_id == route_id)
            .where(Frame.intersection_type.is_not(None))
            .order_by(Frame.segment_id, Frame.frame_id, Frame.camera)
        )
        if segment_id is not None:
            stmt = stmt.where(Frame.segment_id == segment_id)
        if types:
            stmt = stmt.where(Frame.intersection_type.in_(types))
        seen: set[tuple[int, int]] = set()
        frames: list[dict[str, Any]] = []
        for seg, frame_id, label, details in (await self._session.execute(stmt)).all():
            if (seg, frame_id) in seen:
                continue
            seen.add((seg, frame_id))
            frames.append({"segment_id": seg, "frame_id": frame_id, "intersection_type": label,
                           "intersection_details": details})
        return frames

    async def frame_ids_with_types(self, route_id: str, types: list[str]) -> dict[int, set[int]]:
        # this returns {segment_id: {frame_id, ...}} for frames whose label is one of types (used by exports)
        stmt = (
            select(Frame.segment_id, Frame.frame_id)
            .where(Frame.route_id == route_id)
            .where(Frame.intersection_type.in_(types))
        )
        allowed: dict[int, set[int]] = {}
        for seg, frame_id in (await self._session.execute(stmt)).all():
            allowed.setdefault(seg, set()).add(frame_id)
        return allowed

    async def labels_for_route(self, route_id: str) -> dict[int, dict[int, str]]:
        # this returns {segment_id: {frame_id: label}} for every labeled frame (written into exports)
        stmt = (
            select(Frame.segment_id, Frame.frame_id, Frame.intersection_type)
            .where(Frame.route_id == route_id)
            .where(Frame.intersection_type.is_not(None))
        )
        labels: dict[int, dict[int, str]] = {}
        for seg, frame_id, label in (await self._session.execute(stmt)).all():
            labels.setdefault(seg, {})[frame_id] = label
        return labels
