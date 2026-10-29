import asyncio
from pathlib import Path
import logging
import signal
import shutil

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models.segment_dir import SegmentDir
from db.enums import ArtifactKind, ArtifactRole, SegmentStatus
from db.models.route import Route
from db.models.segment import Segment
from db.url import build_database_url
from repositories.frame_repository import FrameRepository
from repositories.route_repository import RouteRepository
from repositories.segment_repository import SegmentRepository
from repositories.frame_artifact_repository import FrameArtifactRepository
from repositories.artifact_repository import ArtifactRepository
from repositories.segment_artifact_repository import SegmentArtifactRepository
from services.frame_artifact_service import FrameArtifactService
from services.frame_service import FrameService
from services.frame_uploader_service import FrameUploaderService
from services.minio_service import MinioService
from services.route_service import RouteService, RouteStatus
from services.segment_service import SegmentService
from services.artifact_service import ArtifactService
from services.segment_artifact_service import SegmentArtifactService
from utilities.camera_type_utilities import folder_name_to_camera_type
from utilities.directory_utilities import does_directory_have_more_than_n_items, get_subdirectories
from utilities.file_utilities import get_pngs_in_directory

POLL_INTERVAL_SECONDS = 2.0
DATA_ROOT = Path("/app/data")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

async def _mark_stale_uploading_segments_as_failed(route_service: RouteService, segment_service: SegmentService):
    logging.info("Checking for stale segments")
    stale_segments = await segment_service.get_segments_by_status(status=SegmentStatus.UPLOADING)
    if not stale_segments:
        logging.info("No stale routes detected on startup")
        return

    for segment in stale_segments:
        await segment_service.set_status(
            route_id=segment.route_id,
            segment_id=segment.segment_id,
            status=SegmentStatus.FAILED
        )
        route = await route_service.get_route(
            route_id=segment.route_id
        )
        if route is not None and route.file_path is not None:
            shutil.rmtree(DATA_ROOT / route.file_path / str(segment.segment_id))

        logger.warning(f"Marked stale segment as failed on startup: {segment}")



def get_list_of_segment_dirs(route_data_path: Path):
    """
    Assumes that data is in format:
    `route_data_path/segment_number/camera_view/images`
    """

    segment_dirs: list[SegmentDir] = []

    subdirectories = get_subdirectories(route_data_path)
    for subdirectory in subdirectories:
        segment_num = int(subdirectory.name)
        if does_directory_have_more_than_n_items(path=subdirectory, n=20):
            segment_dirs.append(
                SegmentDir(
                    path=subdirectory,
                    segment_num=segment_num
                )
            )

    return segment_dirs

def get_segment_camera_views(segment_path: Path) -> list[str]:
    camera_views = [subdirectory.name for subdirectory in get_subdirectories(segment_path)]
    return camera_views


async def upload_segment(
    segment: Segment,
    segment_path: Path,
    segment_service: SegmentService,
    frame_uploader_service: FrameUploaderService,
    artifact_service: ArtifactService,
    segment_artifact_service: SegmentArtifactService,
    session: AsyncSession,
):
    logging.info(f"Uploading segment {segment}")
    minio_service = MinioService()

    for camera_view_folder_name in get_segment_camera_views(segment_path=segment_path):
        camera_view = folder_name_to_camera_type(folder_name=camera_view_folder_name)
        for image_path in get_pngs_in_directory(dir=segment_path / camera_view_folder_name):
            frame_number = int(image_path.name.split(".")[0])
            await frame_uploader_service.create_frame(
                segment=segment,
                camera_view=camera_view,
                frame_number=frame_number,
                frame_path=image_path
            )
            await session.commit()

    # upload logs
    log_path = segment_path / "logs.json"
    log_upload_result = minio_service.put_segment_log(
        segment=segment,
        log_path=log_path
    )
    log_artifact = await artifact_service.create_artifact(
        bucket=log_upload_result.bucket_name,
        object_key=log_upload_result.object_name,
        kind=ArtifactKind.JSON,
    )
    await segment_artifact_service.create_segment_artifact(
        route_id=segment.route_id,
        segment_id=segment.segment_id,
        artifact_id=log_artifact.artifact_id,
        role=ArtifactRole.SEGMENT_LOG,
    )
    await session.commit()

    await segment_service.set_status(route_id=segment.route_id, segment_id=segment.segment_id, status=SegmentStatus.UPLOADED)
    await session.commit()
    logging.info(f"Uploaded segment {segment}")



async def _process_segment(
    segment: Segment,
    route_service: RouteService,
    segment_service: SegmentService,
    frame_uploader_service: FrameUploaderService,
    artifact_service: ArtifactService,
    segment_artifact_service: SegmentArtifactService,
    session: AsyncSession,
):

    logging.info(f"Processing segment {segment}")
    # We set the route status to uploading as soon as we start uploading any segments
    await route_service.set_status(route_id=segment.route_id, status=RouteStatus.UPLOADING)
    await segment_service.set_status(
        route_id=segment.route_id,
        segment_id=segment.segment_id,
        status=SegmentStatus.UPLOADING
    )

    try:
        route = await route_service.get_route(route_id=segment.route_id)
        if not route:
            raise ValueError(f"Could not find route with id {segment.route_id} for segment {segment}")
        if not route.file_path:
            await route_service.set_status(route_id=route.route_id, status=RouteStatus.FAILED)
            await session.commit()
            raise ValueError(f"Route {route.route_id} has no file_path")

        segment_path = DATA_ROOT / route.file_path / str(segment.segment_id)
        route_path = DATA_ROOT / route.file_path 
        try :
            await upload_segment(
                segment=segment,
                segment_path=segment_path,
                segment_service=segment_service,
                frame_uploader_service=frame_uploader_service,
                artifact_service=artifact_service,
                segment_artifact_service=segment_artifact_service,
                session=session
            )

            logging.info("Deleting Data Files")
            shutil.rmtree(segment_path)

            await segment_service.set_status(
                route_id=segment.route_id,
                segment_id=segment.segment_id,
                status=SegmentStatus.UPLOADED
            )
            await session.commit()
            logging.info(f"Processed segment {segment}")
        except Exception as e:
            logging.error(f"Failed to process segment {segment}", e)
            shutil.rmtree(segment_path)
            await segment_service.set_status(
                route_id=segment.route_id,
                segment_id=segment.segment_id,
                status=SegmentStatus.FAILED
            )
            await session.commit()

        if (await are_all_segments_for_route_processed(route=route, segment_service=segment_service)):
            logging.info(f"All segments for {route} processed. Marking segment as uploaded")
            shutil.rmtree(route_path)
            await route_service.set_status(route_id=route.route_id, status=RouteStatus.UPLOADED)
            await session.commit()
        else:
            logging.info(f"All segments for {route} are not processed. Leaving status as 'uploading'")

    except Exception as e:
        logging.error("Error processing route", e)

        await session.rollback()




async def are_all_segments_for_route_processed(route: Route, segment_service: SegmentService):
    """
    Returns True when all the segments for a route are either UPLOADED or FAILED
    """
    segments_for_route = await segment_service.get_segments_by_route(route_id=route.route_id)

    for segment in segments_for_route:
        logging.info(f"status, {segment.status}")
        if segment.status in [SegmentStatus.DOWNLOAD_QUEUE, SegmentStatus.DOWNLOADING, SegmentStatus.UPLOAD_QUEUE, SegmentStatus.UPLOADING]:
            return False

    return True


async def main():
    logger.info("Creating DB engine")
    engine = create_async_engine(build_database_url(), pool_pre_ping=True)
    SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
    logger.info("DB engine created")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        async with SessionLocal() as session:
            route_repository = RouteRepository(session=session)
            route_service = RouteService(route_repository=route_repository)
            segment_repository = SegmentRepository(session=session)
            segment_service = SegmentService(segment_repository=segment_repository)
            frame_repository = FrameRepository(session=session)
            frame_service = FrameService(frame_repository=frame_repository)
            frame_artifact_repository = FrameArtifactRepository(session=session)
            frame_artifact_service = FrameArtifactService(frame_artifact_repository=frame_artifact_repository)
            artifact_repository = ArtifactRepository(session=session)
            artifact_service = ArtifactService(artifact_repository=artifact_repository)
            segment_artifact_repository = SegmentArtifactRepository(session=session)
            segment_artifact_service = SegmentArtifactService(segment_artifact_repository=segment_artifact_repository)
            frame_uploader_service = FrameUploaderService(
                frame_service=frame_service,
                frame_artifact_service=frame_artifact_service,
                artifact_service=artifact_service
            )

            await _mark_stale_uploading_segments_as_failed(
                route_service=route_service,
                segment_service=segment_service
            )
            await session.commit()

            while not stop_event.is_set():
                segment_to_process = await segment_service.get_next_segment_by_status(status=SegmentStatus.UPLOAD_QUEUE)

                if segment_to_process is None:
                    logging.info("No segments found...")
                    await session.rollback()
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                await _process_segment(
                    segment=segment_to_process,
                    route_service=route_service,
                    segment_service=segment_service,
                    frame_uploader_service=frame_uploader_service,
                    artifact_service=artifact_service,
                    segment_artifact_service=segment_artifact_service,
                    session=session
                )
    finally:
        await engine.dispose()
        logger.info("Worker shutdown complete")



if __name__ == "__main__":
    asyncio.run(main())
