import asyncio
import signal

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.url import build_database_url
from intersections.camera import TrafficLightDetector
from intersections.labels import ClassifierConfig
from intersections.osm import OsmMapSource
from repositories.route_repository import RouteRepository
from services.audit_service import (
    OUTCOME_FAILURE,
    OUTCOME_SUCCESS,
    OUTCOME_WARNING,
    configure_audit,
    record_audit,
)
from services.intersection_service import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    IntersectionLabelingService,
    needs_labeling,
    now_iso,
)
from services.minio_service import MinioService
from services.route_service import RouteService
from utilities.error_utilities import describe_exception, error_code_of, record_failure
from utilities.logging_utilities import configure_logging
from utilities.service_builder_utilities import (
    build_artifact_service,
    build_frame_artifact_service,
    build_segment_artifact_service,
)

POLL_INTERVAL_SECONDS = 5.0

logger = configure_logging("intersection_worker")


async def _reset_interrupted_runs(route_service: RouteService) -> None:
    # this puts routes that were being labeled when the worker stopped back in the queue
    for route in await route_service.list_routes():
        info = route.intersections or {}
        if info.get("status") == STATUS_RUNNING:
            logger.warning("Re-queueing interrupted intersection labeling for route %s", route.route_id)
            await route_service.set_intersection_status(
                route.route_id, {**info, "status": STATUS_PENDING, "note": "worker restarted while labeling"}
            )


def _outcome(summary: dict) -> tuple[str, str | None]:
    # this turns a finished summary into an audit outcome: a warning when labels are less reliable
    total = summary.get("frames_total", 0)
    with_gps = summary.get("frames_with_gps", 0)
    problems = []
    if total and with_gps / total < 0.5:
        problems.append(f"only {with_gps} of {total} frames had a gps position (the rest are labeled unknown)")
    camera_error = (summary.get("camera") or {}).get("error")
    if camera_error:
        problems.append(f"camera check skipped: {camera_error}")
    if problems:
        return OUTCOME_WARNING, "; ".join(problems)
    return OUTCOME_SUCCESS, None


async def main() -> None:
    logger.info("Starting intersection_worker")
    config = ClassifierConfig.from_env()
    engine = create_async_engine(build_database_url(), pool_pre_ping=True)
    SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
    configure_audit(SessionLocal, source="intersection_worker")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    # the camera model is shared by every route this worker labels
    def detector_factory() -> TrafficLightDetector:
        return TrafficLightDetector(config.camera_model, config.camera_min_score, config.camera_min_light_height)

    try:
        async with SessionLocal() as session:
            route_service = RouteService(route_repository=RouteRepository(session=session))
            service = IntersectionLabelingService(
                session=session,
                route_service=route_service,
                segment_artifact_service=build_segment_artifact_service(session=session),
                frame_artifact_service=build_frame_artifact_service(session=session),
                artifact_service=build_artifact_service(session=session),
                minio_service=MinioService(),
                map_source=OsmMapSource(config),
                config=config,
                detector_factory=detector_factory,
            )

            await _reset_interrupted_runs(route_service)
            await session.commit()
            logger.info(
                "Ready: labeling uploaded routes (camera check %s, map data from %s)",
                "on" if config.camera_check else "off",
                config.overpass_url,
            )

            while not stop_event.is_set():
                # this block finds the next uploaded route that still needs labels
                routes = [r for r in await route_service.list_routes() if needs_labeling(r)]
                await session.rollback()
                if not routes:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                route_id = routes[-1].route_id  # list_routes is newest first, so this takes the oldest
                logger.info("Labeling intersections for route %s", route_id)
                try:
                    summary = await service.label_route(route_id)
                    outcome, warning = _outcome(summary)
                    logger.info("Labeled route %s: %s", route_id, summary.get("counts"))
                    await record_audit(
                        "intersections.finished", outcome,
                        entity_type="route", entity_id=route_id, route_id=route_id, message=warning,
                        details={"counts": summary.get("counts"), "intersections": summary.get("intersections_passed"),
                                 "camera_sampled_frames": (summary.get("camera") or {}).get("sampled_frames")},
                    )
                except Exception as e:
                    error = describe_exception(e)
                    code = error_code_of(e)
                    logger.exception("Intersection labeling failed for route %s", route_id)
                    await record_failure(
                        session, logger, f"intersections for route {route_id}",
                        lambda: route_service.set_intersection_status(
                            route_id,
                            {"status": STATUS_FAILED, "error": error, "error_code": code,
                             "finished_at": now_iso()},
                        ),
                    )
                    await record_audit(
                        "intersections.finished", OUTCOME_FAILURE,
                        entity_type="route", entity_id=route_id, route_id=route_id,
                        message=error, error_code=code,
                    )

            logger.info("Stop event received, shutting down worker")
    finally:
        await engine.dispose()
        logger.info("Worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
