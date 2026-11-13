import asyncio
import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from db.enums import ArtifactRole, CameraType, RouteStatus
from db.models.route import Route
from intersections.camera import TrafficLightDetector
from intersections.classifier import (
    CameraEvidence,
    FramePoint,
    IntersectionMatcher,
    classify_frames,
    count_labels,
    select_camera_samples,
)
from intersections.gps import positions_by_frame_id
from intersections.labels import CLASSIFIER_VERSION, SIGNALIZED, ClassifierConfig
from intersections.osm import OsmMapSource
from repositories.intersection_repository import FrameRef, IntersectionRepository
from services.artifact_service import ArtifactService
from services.frame_artifact_service import FrameArtifactService
from services.minio_service import MinioService
from services.route_service import RouteService
from services.segment_artifact_service import SegmentArtifactService

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# the camera with the best view of traffic lights is tried first
CAMERA_PREFERENCE = [CameraType.FRONT_REGULAR, CameraType.FRONT_WIDE]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def needs_labeling(route: Route) -> bool:
    # this decides if the worker should label a route: it must be uploaded, and either never labeled,
    # queued for a re-run (pending), or labeled by an older version of the rules
    if route.status != RouteStatus.UPLOADED:
        return False
    info = route.intersections
    if not info:
        return True
    if info.get("status") == STATUS_PENDING:
        return True
    return info.get("status") == STATUS_DONE and int(info.get("version", 0)) < CLASSIFIER_VERSION


class IntersectionLabelingService:
    # this labels every frame of a route as signalized / unsignalized / non-intersection (or unknown)

    def __init__(
        self,
        session: AsyncSession,
        route_service: RouteService,
        segment_artifact_service: SegmentArtifactService,
        frame_artifact_service: FrameArtifactService,
        artifact_service: ArtifactService,
        minio_service: MinioService,
        map_source: OsmMapSource,
        config: ClassifierConfig,
        detector_factory: Callable[[], TrafficLightDetector] | None = None,
    ) -> None:
        self.session = session
        self.route_service = route_service
        self.segment_artifact_service = segment_artifact_service
        self.frame_artifact_service = frame_artifact_service
        self.artifact_service = artifact_service
        self.minio_service = minio_service
        self.map_source = map_source
        self.config = config
        self.repository = IntersectionRepository(session)
        self._detector_factory = detector_factory
        self._detector: TrafficLightDetector | None = None
        self._detector_error: str | None = None

    def _get_detector(self) -> TrafficLightDetector | None:
        # this loads the camera model once; if it can't load, the camera check is skipped and the reason recorded
        if self._detector is not None or self._detector_error is not None:
            return self._detector
        if not self.config.camera_check or self._detector_factory is None:
            self._detector_error = "camera check turned off"
            return None
        try:
            self._detector = self._detector_factory()
        except Exception as e:
            logger.exception("Could not load the camera check model; labeling with map data only")
            self._detector_error = f"{type(e).__name__}: {e}"
        return self._detector

    async def _segment_positions(self, route_id: str, segment_id: int, work_dir: Path) -> dict[int, tuple[float, float] | None]:
        # this downloads one segment's logs.json and reads the gps position of every frame
        segment_artifact = await self.segment_artifact_service.get_segment_artifact(
            route_id=route_id, segment_id=segment_id, role=ArtifactRole.SEGMENT_LOG
        )
        if segment_artifact is None:
            logger.warning("No logs.json for route=%s segment=%s; its frames will be labeled unknown", route_id, segment_id)
            return {}
        artifact = await self.artifact_service.get_artifact(segment_artifact.artifact_id)
        if artifact is None:
            return {}
        log_path = work_dir / f"logs_{segment_id}.json"
        await asyncio.to_thread(self.minio_service.download_artifact, artifact, log_path)
        try:
            entries = json.loads(log_path.read_text(encoding="utf-8"))
        finally:
            log_path.unlink(missing_ok=True)
        return positions_by_frame_id(entries if isinstance(entries, list) else [])

    async def _camera_evidence(
        self,
        samples: dict[str, list[tuple[int, int]]],
        refs_by_key: dict[tuple[int, int], list[FrameRef]],
        work_dir: Path,
    ) -> tuple[dict[str, CameraEvidence], int]:
        # this runs the traffic light detector on the sampled frames of each intersection
        detector = self._get_detector()
        evidence: dict[str, CameraEvidence] = {}
        if detector is None:
            return evidence, 0
        sampled_total = 0
        for intersection_id, keys in samples.items():
            result = CameraEvidence()
            for key in keys:
                refs = sorted(refs_by_key.get(key, []), key=lambda r: CAMERA_PREFERENCE.index(r.camera)
                              if r.camera in CAMERA_PREFERENCE else len(CAMERA_PREFERENCE))
                if not refs:
                    continue
                image_path = await self._download_frame_image(refs[0], work_dir)
                if image_path is None:
                    continue
                try:
                    observation = await asyncio.to_thread(detector.observe, image_path)
                except Exception:
                    logger.exception("Camera check failed on frame %s", key)
                    continue
                finally:
                    image_path.unlink(missing_ok=True)
                result.sampled += 1
                sampled_total += 1
                if observation.traffic_lights > 0:
                    result.signal_frames += 1
                    result.max_signal_score = max(result.max_signal_score, observation.max_light_score)
                if observation.stop_signs > 0:
                    result.stop_frames += 1
            evidence[intersection_id] = result
        return evidence, sampled_total

    async def _download_frame_image(self, ref: FrameRef, work_dir: Path) -> Path | None:
        frame_artifact = await self.frame_artifact_service.get_frame_artifact(
            frame_pk=ref.frame_pk, role=ArtifactRole.FRAME_IMAGE
        )
        if frame_artifact is None:
            return None
        artifact = await self.artifact_service.get_artifact(frame_artifact.artifact_id)
        if artifact is None:
            return None
        path = work_dir / f"frame_{ref.frame_pk}.png"
        await asyncio.to_thread(self.minio_service.download_artifact, artifact, path)
        return path

    async def label_route(self, route_id: str) -> dict[str, Any]:
        # this labels a whole route and returns the summary stored in the route's meta
        started_at = now_iso()
        await self.route_service.set_intersection_status(
            route_id, {"status": STATUS_RUNNING, "version": CLASSIFIER_VERSION, "started_at": started_at}
        )
        await self.session.commit()

        refs = await self.repository.list_frame_refs(route_id)
        refs_by_key: dict[tuple[int, int], list[FrameRef]] = {}
        for ref in refs:
            refs_by_key.setdefault((ref.segment_id, ref.frame_id), []).append(ref)
        segment_ids = sorted({ref.segment_id for ref in refs})

        with tempfile.TemporaryDirectory(prefix="intersections_") as tmp:
            work_dir = Path(tmp)

            # this block reads the gps position of every frame from each segment's logs.json
            frames: list[FramePoint] = []
            for segment_id in segment_ids:
                positions = await self._segment_positions(route_id, segment_id, work_dir)
                for (seg, frame_id) in sorted(k for k in refs_by_key if k[0] == segment_id):
                    frames.append(FramePoint(seg, frame_id, positions.get(frame_id)))
            points = [f.position for f in frames if f.position is not None]
            logger.info("Route %s: %d frames, %d with gps", route_id, len(frames), len(points))

            # this block gets the intersections near the route from openstreetmap
            intersections = await asyncio.to_thread(self.map_source.intersections_for_points, points) if points else []
            matcher = IntersectionMatcher(intersections, self.config.approach_radius_m)
            passed = {
                match[1].id
                for f in frames if f.position is not None
                for match in [matcher.nearest(f.position, self.config.intersection_radius_m)] if match
            }
            intersections = [i for i in intersections if i.id in passed]
            matcher = IntersectionMatcher(intersections, self.config.approach_radius_m)

            # this block runs the camera check on a few frames per intersection the car went through
            evidence: dict[str, CameraEvidence] = {}
            sampled = 0
            if intersections and self.config.camera_check:
                samples = select_camera_samples(frames, matcher, self.config)
                evidence, sampled = await self._camera_evidence(samples, refs_by_key, work_dir)

        labels = classify_frames(frames, intersections, evidence, self.config)

        # this block saves the label on every frame row (both cameras get the same label)
        rows = [
            {"frame_pk": ref.frame_pk, "intersection_type": label.label, "intersection_details": label.details}
            for key, label in labels.items()
            for ref in refs_by_key.get(key, [])
        ]
        await self.repository.clear_labels(route_id)
        await self.repository.set_labels(rows)

        counts = count_labels(labels.values())
        summary = {
            "status": STATUS_DONE,
            "version": CLASSIFIER_VERSION,
            "started_at": started_at,
            "finished_at": now_iso(),
            "counts": counts,
            "frames_total": len(frames),
            "frames_with_gps": len(points),
            "intersections_passed": len(intersections),
            "signalized_intersections": len({
                l.details.get("intersection_id") for l in labels.values() if l.label == SIGNALIZED
            }),
            "camera": {
                "enabled": self.config.camera_check,
                "sampled_frames": sampled,
                "checked_intersections": sum(1 for e in evidence.values() if e.sampled),
                "error": self._detector_error if self.config.camera_check else None,
            },
        }
        await self.route_service.set_intersection_status(route_id, summary)
        await self.session.commit()
        return summary
