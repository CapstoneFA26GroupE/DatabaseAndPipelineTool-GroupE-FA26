import asyncio
import logging
import shutil
import signal
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cvat_annotation_functions.cvat_detection_loader import (
    load_builtin_cvat_detection_plugins,
)
from cvat_annotation_functions.cvat_detection_registry import build_cvat_detection_from_key
from db.enums import ArtifactKind, JobSegmentRunStatus, JobStatus
from db.models.job_definition import JobDefinition
from db.models.job_run import JobRun
from db.models.job_segment_run import JobSegmentRun
from db.url import build_database_url
from repositories.artifact_repository import ArtifactRepository
from repositories.frame_artifact_repository import FrameArtifactRepository
from repositories.frame_repository import FrameRepository
from services.artifact_service import ArtifactService
from services.cvat_service import CVATService
from services.frame_artifact_downloader_service import FrameArtifactDownloaderService
from services.frame_artifact_service import FrameArtifactService
from services.frame_service import FrameService
from services.minio_service import MinioService
from services.errors import SegmentNotFoundError
from services.job_definition_service import JobDefinitionService
from services.job_run_service import JobRunService
from services.job_segment_run_service import JobSegmentRunService
from services.segment_artifact_download_service import SegmentArtifactDownloadService
from services.segment_service import SegmentService
from utilities.service_builder_utilities import (
    build_job_definition_service,
    build_job_run_service,
    build_job_segment_run_service,
    build_segment_service,
)


POLL_INTERVAL_SECONDS = 1.0
DATA_DIR = Path("/app/cvat_share")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# Helpers
async def _mark_stale_running_jobs_as_failed(
    job_run_service: JobRunService, job_segment_run_service: JobSegmentRunService
):
    # Delete all temp files that might have been left over
    for item in DATA_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    stale_jobs = await job_run_service.get_job_runs_by_status(status=JobStatus.RUNNING)
    if not stale_jobs:
        return


    # for all of the stale jobs mark both the job_run and job_segment_run as failed
    for job in stale_jobs:
        await job_run_service.set_error(
            job_run_num=job.job_run_num,
            job_def_id=job.job_def_id,
            route_id=job.route_id,
            camera=job.camera,
            error="Job marked as stale"
        )

        segments = await job_segment_run_service.get_segments_by_job_run(
            job_run_num=job.job_run_num,
            job_def_id=job.job_def_id,
            route_id=job.route_id,
            camera=job.camera,
        )
        for segment in segments:
            # only stale if it was actively queued or running, if a segment was completed don't set it to failed
            if segment.status in (
                JobSegmentRunStatus.RUNNING,
                JobSegmentRunStatus.QUEUED,
            ):
                await job_segment_run_service.set_status(
                    job_run_num=segment.job_run_num,
                    job_def_id=segment.job_def_id,
                    route_id=segment.route_id,
                    segment_id=segment.segment_id,
                    camera=job.camera,
                    status=JobSegmentRunStatus.FAILED,
                )


async def create_job_segment_runs_for_job_run(
    job_run: JobRun,
    job_segment_run_service: JobSegmentRunService,
    segment_service: SegmentService,
) -> list[JobSegmentRun]:
    segments = await segment_service.get_segments_by_route(route_id=job_run.route_id)

    job_segment_runs: list[JobSegmentRun] = []
    for segment in segments:
        job_segment_run = await job_segment_run_service.create_job_segment_run(
            job_run_num=job_run.job_run_num,
            job_def_id=job_run.job_def_id,
            route_id=job_run.route_id,
            camera=job_run.camera,
            segment_id=segment.segment_id,
        )

        job_segment_runs.append(job_segment_run)

    return job_segment_runs


async def process_job_segment_run(
    job_definition: JobDefinition,
    job_segment_run: JobSegmentRun,
    job_segment_run_service: JobSegmentRunService,
    segment_artifact_download_service: SegmentArtifactDownloadService,
    segment_service: SegmentService,
    artifact_service: ArtifactService,
    cvat_service: CVATService,
    minio_service: MinioService,
    session: AsyncSession,
):
    logging.info(f"Processing job segment run {job_segment_run}")

    unique_id = str(uuid4())
    segment_dir = DATA_DIR / unique_id
    try:
        await job_segment_run_service.set_status(
            job_run_num=job_segment_run.job_run_num,
            job_def_id=job_segment_run.job_def_id,
            route_id=job_segment_run.route_id,
            segment_id=job_segment_run.segment_id,
            camera=job_segment_run.camera,
            status=JobSegmentRunStatus.RUNNING,
        )
        await session.commit()

        segment = await segment_service.get_segment(
            route_id=job_segment_run.route_id, segment_id=job_segment_run.segment_id
        )

        if not segment:
            raise SegmentNotFoundError(
                route_id=job_segment_run.route_id, segment_id=job_segment_run.segment_id
            )

        await segment_artifact_download_service.download_segment_frames(
            segment=segment, dest_path=segment_dir, camera=job_segment_run.camera
        )

        cvat_function = build_cvat_detection_from_key(
            key=job_definition.implementation_key,
            config=job_definition.config,
        )

        segment_detection_file_path = cvat_service.get_detections_for_segment(
            segment_dir=segment_dir,
            cvat_function=cvat_function,
            output_dir=Path(segment_dir)
        )
        object_write_result = minio_service.put_job_segment_run_data(
            job_segment_run=job_segment_run,
            file_path=segment_detection_file_path
        )

        artifact = await artifact_service.create_artifact(
            bucket=minio_service.bucket_name,
            object_key=object_write_result.object_name,
            kind=ArtifactKind.JSON
        )



        job_segment_run.artifact_id = artifact.artifact_id

        await job_segment_run_service.set_status(
            job_run_num=job_segment_run.job_run_num,
            job_def_id=job_segment_run.job_def_id,
            route_id=job_segment_run.route_id,
            segment_id=job_segment_run.segment_id,
            camera=job_segment_run.camera,
            status=JobSegmentRunStatus.SUCCEEDED,
        )
        await session.commit()

    except Exception as e:
        logging.error(f"Failed to process job segment run {job_segment_run}", e)
        await job_segment_run_service.set_status(
            job_run_num=job_segment_run.job_run_num,
            job_def_id=job_segment_run.job_def_id,
            route_id=job_segment_run.route_id,
            segment_id=job_segment_run.segment_id,
            camera=job_segment_run.camera,
            status=JobSegmentRunStatus.FAILED,
        )
        await session.commit()
    finally:
        if segment_dir.exists():
            logging.info(f"Removing Dir: {segment_dir}")
            shutil.rmtree(segment_dir)


async def _process_job_run(
    job_run: JobRun,
    job_definition_service: JobDefinitionService,
    job_run_service: JobRunService,
    segment_service: SegmentService,
    job_segment_run_service: JobSegmentRunService,
    segment_artifact_download_service: SegmentArtifactDownloadService,
    cvat_service: CVATService,
    minio_service: MinioService,
    artifact_service: ArtifactService,
    session: AsyncSession,
):
    logging.info(f"Processing job {job_run}")
    try:
        job_definition = await job_definition_service.get_job_definition(job_def_id=job_run.job_def_id)
        if job_definition is None:
            raise ValueError(f"Could not find job definition {job_run.job_def_id}")

        # Create job_segment_runs for each segment
        # for each segment in segments, process segment
        job_segment_runs = await create_job_segment_runs_for_job_run(
            job_run=job_run,
            job_segment_run_service=job_segment_run_service,
            segment_service=segment_service,
        )
        await session.commit()

        for job_segment_run in job_segment_runs:
            await process_job_segment_run(
                job_definition=job_definition,
                job_segment_run=job_segment_run,
                job_segment_run_service=job_segment_run_service,
                segment_service=segment_service,
                segment_artifact_download_service=segment_artifact_download_service,
                cvat_service=cvat_service,
                minio_service=minio_service,
                artifact_service=artifact_service,
                session=session,
            )

        logging.info(f"Processing job suceeded: {job_run}")
        await job_run_service.set_status(
            job_run_num=job_run.job_run_num,
            job_def_id=job_run.job_def_id,
            route_id=job_run.route_id,
            camera=job_run.camera,
            status=JobStatus.SUCCEEDED,
        )
        await session.commit()

    except Exception as e:
        logging.error(f"Job Processing Failed: {job_run}", e)
        await job_run_service.set_status(
            job_run_num=job_run.job_run_num,
            job_def_id=job_run.job_def_id,
            route_id=job_run.route_id,
            camera=job_run.camera,
            status=JobStatus.FAILED,
        )
        await session.commit()


async def main():
    load_builtin_cvat_detection_plugins()

    # create session to access database
    engine = create_async_engine(build_database_url(), pool_pre_ping=True)
    SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

    stop_event = asyncio.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        async with SessionLocal() as session:
            job_definition_service = build_job_definition_service(session=session)
            job_run_service = build_job_run_service(session=session)
            job_segment_run_service = build_job_segment_run_service(session=session)
            frame_repository = FrameRepository(session=session)
            frame_service = FrameService(frame_repository=frame_repository)
            frame_artifact_repository = FrameArtifactRepository(session=session)
            frame_artifact_service = FrameArtifactService(frame_artifact_repository=frame_artifact_repository)
            artifact_repository = ArtifactRepository(session=session)
            artifact_service = ArtifactService(artifact_repository=artifact_repository)
            segment_service = build_segment_service(session=session)
            minio_service = MinioService()
            cvat_service = CVATService()
            frame_artifact_downloader_service = FrameArtifactDownloaderService(
                frame_service=frame_service,
                frame_artifact_service=frame_artifact_service,
                artifact_service=artifact_service,
                minio_service=minio_service
            )
            segment_artifact_download_service = SegmentArtifactDownloadService(
                frame_service=frame_service,
                frame_artifact_downloader_service=frame_artifact_downloader_service
            )

            await _mark_stale_running_jobs_as_failed(
                job_run_service, job_segment_run_service
            )
            await session.commit()

            while not stop_event.is_set():
                job_run = await job_run_service.claim_next_queued_job()
                if job_run is None:
                    await session.rollback()
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue
                await session.commit()

                await _process_job_run(
                    job_run=job_run,
                    job_definition_service=job_definition_service,
                    job_run_service=job_run_service,
                    segment_service=segment_service,
                    job_segment_run_service=job_segment_run_service,
                    segment_artifact_download_service=segment_artifact_download_service,
                    cvat_service=cvat_service,
                    minio_service=minio_service,
                    artifact_service=artifact_service,
                    session=session,
                )

            logger.info("Stop event received, shutting down worker")
    finally:
        executor.shutdown(wait=False)
        await engine.dispose()
        logger.info("Worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
