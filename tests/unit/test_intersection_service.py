# tests the whole route labeling flow against a real (sqlite) database with fake map, storage and camera
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.enums import CameraType, RouteStatus, SegmentStatus
from db.models.frame import Frame
from db.models.route import Route
from db.models.segment import Segment
from intersections.camera import CameraObservation
from intersections.labels import SIGNALIZED, NON_INTERSECTION, UNKNOWN, UNSIGNALIZED, ClassifierConfig
from intersections.osm import Intersection
from repositories.intersection_repository import IntersectionRepository
from repositories.route_repository import RouteRepository
from services.intersection_service import IntersectionLabelingService, needs_labeling, next_route_to_label
from services.route_service import RouteService

# run every async test with pytest-asyncio (the test container uses its default "strict" mode)
pytestmark = pytest.mark.asyncio

ROUTE = "abc|0000-route"
LAT0, LON0 = 35.2, -97.44
DEG_PER_M = 1 / 111_320


def lon_at(east_m):
    return LON0 + east_m * DEG_PER_M / 0.8181


class FakeSegmentArtifacts:
    async def get_segment_artifact(self, route_id, segment_id, role):
        return SimpleNamespace(artifact_id=f"log-{segment_id}")


class FakeFrameArtifacts:
    async def get_frame_artifact(self, frame_pk, role):
        return SimpleNamespace(artifact_id=f"img-{frame_pk}")


class FakeArtifacts:
    async def get_artifact(self, artifact_id):
        return SimpleNamespace(id=artifact_id)


class FakeMinio:
    # segment 0: a car drives east through two intersections (100 m apart); frame 99 has no gps fix
    def download_artifact(self, artifact, dest_path: Path):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if artifact.id.startswith("log-"):
            entries = [{"frame_id": i, "vehicle_state": {"positionGeodetic": {
                "value": [LAT0, lon_at(-50 + i * 10), 300.0], "valid": True}}} for i in range(21)]
            entries.append({"frame_id": 99, "vehicle_state": {"status": "uninitialized"}})
            dest_path.write_text(json.dumps(entries))
        else:
            dest_path.write_bytes(b"png")


class FakeMap:
    def intersections_for_points(self, points):
        return [
            Intersection("osm-signal", LAT0, lon_at(0), [1], ["primary"], map_signalized=True, signal_node_ids=[7]),
            Intersection("osm-stop", LAT0, lon_at(100), [2], ["residential"], map_signalized=False, controls=["stop"]),
            Intersection("osm-far", LAT0 + 0.01, LON0, [3], ["residential"], map_signalized=False),
        ]


class FakeDetector:
    # sees lights near the first intersection only
    def __init__(self):
        self.calls = 0

    def observe(self, path):
        self.calls += 1
        return CameraObservation(traffic_lights=1 if self.calls <= 3 else 0, stop_signs=0, max_light_score=0.9)


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    async with engine.begin() as conn:
        for table in (Route.__table__, Segment.__table__, Frame.__table__):
            await conn.run_sync(table.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Route(route_id=ROUTE, status=RouteStatus.UPLOADED))
        now = datetime.now(timezone.utc)
        session.add(Segment(route_id=ROUTE, segment_id=0, start_time=now, end_time=now, status=SegmentStatus.UPLOADED))
        pk = 1
        for frame_id in list(range(21)) + [99]:
            for camera in (CameraType.FRONT_REGULAR, CameraType.FRONT_WIDE):
                session.add(Frame(frame_pk=pk, route_id=ROUTE, segment_id=0, frame_id=frame_id, camera=camera))
                pk += 1
        await session.commit()
    yield factory
    await engine.dispose()


async def test_label_route_end_to_end(session_factory):
    detector = FakeDetector()
    async with session_factory() as session:
        route_service = RouteService(RouteRepository(session))
        service = IntersectionLabelingService(
            session=session, route_service=route_service,
            segment_artifact_service=FakeSegmentArtifacts(), frame_artifact_service=FakeFrameArtifacts(),
            artifact_service=FakeArtifacts(), minio_service=FakeMinio(), map_source=FakeMap(),
            config=ClassifierConfig(camera_samples_per_intersection=3), detector_factory=lambda: detector,
        )
        assert needs_labeling(await route_service.get_route(ROUTE))
        summary = await service.label_route(ROUTE)

    assert summary["status"] == "done"
    assert summary["frames_total"] == 22 and summary["frames_with_gps"] == 21
    assert summary["intersections_passed"] == 2  # the far one is ignored
    assert summary["camera"]["sampled_frames"] == 6
    assert summary["counts"] == {SIGNALIZED: 7, UNSIGNALIZED: 7, NON_INTERSECTION: 7, UNKNOWN: 1}

    async with session_factory() as session:
        repo = IntersectionRepository(session)
        assert await repo.count_by_segment(ROUTE) == {0: summary["counts"]}
        frames = await repo.list_labeled_frames(ROUTE, types=[SIGNALIZED])
        assert [f["frame_id"] for f in frames] == [2, 3, 4, 5, 6, 7, 8]
        assert frames[0]["intersection_details"]["source"] == "map+camera"
        assert await repo.frame_ids_with_types(ROUTE, [UNSIGNALIZED]) == {0: {12, 13, 14, 15, 16, 17, 18}}
        # both cameras got the same label
        regular = await session.get(Frame, 1)
        wide = await session.get(Frame, 2)
        assert regular.intersection_type == wide.intersection_type == NON_INTERSECTION
        route = await RouteService(RouteRepository(session)).get_route(ROUTE)
        assert route.intersections["status"] == "done" and not needs_labeling(route)


async def test_label_route_without_camera_model_still_labels(session_factory):
    def broken_factory():
        raise RuntimeError("model download failed")

    async with session_factory() as session:
        service = IntersectionLabelingService(
            session=session, route_service=RouteService(RouteRepository(session)),
            segment_artifact_service=FakeSegmentArtifacts(), frame_artifact_service=FakeFrameArtifacts(),
            artifact_service=FakeArtifacts(), minio_service=FakeMinio(), map_source=FakeMap(),
            config=ClassifierConfig(), detector_factory=broken_factory,
        )
        summary = await service.label_route(ROUTE)
    assert summary["status"] == "done"
    assert summary["camera"]["sampled_frames"] == 0
    assert "model download failed" in summary["camera"]["error"]
    assert summary["counts"][SIGNALIZED] == 7  # map data alone still labels it


async def test_next_route_to_label_survives_rollback_and_sees_new_uploads(session_factory):
    # the worker crashed here once: it read route ids after a rollback had made the rows stale
    async with session_factory() as session:
        session.add(Route(route_id="abc|0001-still-uploading", status=RouteStatus.UPLOADING))
        await session.commit()

    async with session_factory() as worker_session:
        route_service = RouteService(RouteRepository(worker_session))
        assert await next_route_to_label(route_service, worker_session) == ROUTE

        # another worker finishes the upload and this one labels the first route
        async with session_factory() as other:
            await RouteService(RouteRepository(other)).set_intersection_status(ROUTE, {"status": "done", "version": 99})
            (await other.get(Route, "abc|0001-still-uploading")).status = RouteStatus.UPLOADED
            await other.commit()

        # the same long-lived session must notice both changes on its next poll
        assert await next_route_to_label(route_service, worker_session) == "abc|0001-still-uploading"
