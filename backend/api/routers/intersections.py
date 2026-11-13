import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session, get_transactional_session
from db.enums import RouteStatus
from intersections.labels import ALL_TYPES, DISPLAY_NAMES
from repositories.intersection_repository import IntersectionRepository
from repositories.route_repository import RouteRepository
from schemas.intersections import IntersectionFrameResponse, IntersectionSummaryResponse
from services.errors import IntersectionsBusyError, InvalidIntersectionTypeError, RouteNotFoundError
from services.intersection_service import STATUS_PENDING, STATUS_RUNNING
from services.route_service import RouteService

logger = logging.getLogger(__name__)

intersections_router = APIRouter(
    prefix="/intersections",
)


def _validate_types(types: list[str] | None) -> list[str] | None:
    # this rejects unknown label names with a clear error
    for value in types or []:
        if value not in ALL_TYPES:
            raise InvalidIntersectionTypeError(value)
    return types or None


@intersections_router.get("/summary", response_model=IntersectionSummaryResponse)
async def get_route_intersection_summary(
    route_id: str,
    session: AsyncSession = Depends(get_session),
) -> IntersectionSummaryResponse:
    # this returns the labeling status of a route and how many frames got each label (total and per segment)
    route = await RouteRepository(session).get_by_id(route_id)
    if route is None:
        raise RouteNotFoundError(route_id)
    info = dict(route.intersections or {})
    if not info:
        info["status"] = STATUS_PENDING if route.status == RouteStatus.UPLOADED else "waiting_for_upload"

    per_segment = await IntersectionRepository(session).count_by_segment(route_id)
    totals: dict[str, int] = {}
    for counts in per_segment.values():
        for label, count in counts.items():
            totals[label] = totals.get(label, 0) + count

    return IntersectionSummaryResponse(
        route_id=route_id,
        status=info.get("status", STATUS_PENDING),
        version=info.get("version"),
        error=info.get("error"),
        error_code=info.get("error_code"),
        started_at=info.get("started_at"),
        finished_at=info.get("finished_at"),
        counts=totals,
        segments=[{"segment_id": seg, "counts": counts} for seg, counts in sorted(per_segment.items())],
        frames_total=info.get("frames_total", 0),
        frames_with_gps=info.get("frames_with_gps", 0),
        frames_gps_interpolated=info.get("frames_gps_interpolated", 0),
        intersections_passed=info.get("intersections_passed", 0),
        signalized_intersections=info.get("signalized_intersections", 0),
        camera=info.get("camera") or {},
        labels=DISPLAY_NAMES,
    )


@intersections_router.get("/frames", response_model=list[IntersectionFrameResponse])
async def list_route_intersection_frames(
    route_id: str,
    segment_id: int | None = None,
    intersection_type: list[str] | None = Query(None, description="Only these labels (repeatable)"),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    # this lists labeled frames in order (one per moment, not per camera), optionally filtered by label
    types = _validate_types(intersection_type)
    if await RouteRepository(session).get_by_id(route_id) is None:
        raise RouteNotFoundError(route_id)
    return await IntersectionRepository(session).list_labeled_frames(route_id, segment_id=segment_id, types=types)


@intersections_router.post("/reclassify", response_model=IntersectionSummaryResponse)
async def reclassify_route_intersections(
    route_id: str,
    session: AsyncSession = Depends(get_transactional_session),
) -> IntersectionSummaryResponse:
    # this queues a route to be labeled again (e.g. after a failure or new map data)
    route_service = RouteService(RouteRepository(session))
    route = await route_service.get_route(route_id)
    if route is None:
        raise RouteNotFoundError(route_id)
    if (route.intersections or {}).get("status") == STATUS_RUNNING:
        raise IntersectionsBusyError(route_id)
    logger.info("Re-queueing intersection labeling for route %s", route_id)
    await route_service.set_intersection_status(route_id, {"status": STATUS_PENDING})
    return IntersectionSummaryResponse(route_id=route_id, status=STATUS_PENDING, labels=DISPLAY_NAMES)
