import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import shutil
import signal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.enums import JobSegmentRunImportStatus
from db.models.job_segment_run_import import JobSegmentRunImport
from db.url import build_database_url
from repositories.artifact_repository import ArtifactRepository
from repositories.frame_artifact_repository import FrameArtifactRepository
from repositories.frame_repository import FrameRepository
from repositories.job_segment_run_repository import JobSegmentRunRepository
from repositories.job_segment_run_import_repository import JobSegmentRunImportRepository
from repositories.segment_repository import SegmentRepository
from services.artifact_service import ArtifactService
from services.cvat_service import CVATService
from services.errors import JobSegmentRunNotFoundError
from services.frame_artifact_downloader_service import FrameArtifactDownloaderService
from services.frame_artifact_service import FrameArtifactService
from services.frame_service import FrameService
from services.job_segment_artifiact_downloader_service import JobSegmentArtifactDownloaderService
from services.job_segment_run_import_service import JobSegmentRunImportService
from services.job_segment_run_service import JobSegmentRunService
from services.minio_service import MinioService
from services.segment_artifact_download_service import SegmentArtifactDownloadService
from services.segment_service import SegmentService
from utilities.cvat_utilities import get_task_url


POLL_INTERVAL_SECONDS = 1.0
DATA_DIR = Path("/app/cvat_share")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

async def _mark_stale_running_jobs_as_failed(job_segment_run_import_service: JobSegmentRunImportService):
    logging.info("Marking stale running jobs as failed")
    stale_jobs = await job_segment_run_import_service.get_by_status(status=JobSegmentRunImportStatus.LOADING)
    for job in stale_jobs:
        logger.warning(f"Stale job: {job} marked as FAILED")

    stale_jobs = await job_segment_run_import_service.get_by_status(status=JobSegmentRunImportStatus.REMOVING)
    for job in stale_jobs:
        logger.warning(f"Stale job: {job} marked as FAILED")
        await job_segment_run_import_service.set_error(
            job_segment_run_import=job,
            error_message="Import job has status 'RUNNING' after worker restart. Marking as stale"
        )

    logger.info("Completed marking stale running jobs as failed.")


async def _process_loading_job(
    job_segment_run_import:JobSegmentRunImport,
    job_segment_run_import_service:JobSegmentRunImportService,
    cvat_service:CVATService,
    job_segment_run_service: JobSegmentRunService,
    job_segment_artifact_downloader_service: JobSegmentArtifactDownloaderService,
    session: AsyncSession
):
    logging.info(f"Processing loading job {job_segment_run_import}")
    await job_segment_run_import_service.set_status(
        job_run_num=job_segment_run_import.job_run_num,
        job_def_id=job_segment_run_import.job_def_id,
        route_id=job_segment_run_import.route_id,
        segment_id=job_segment_run_import.segment_id,
        camera=job_segment_run_import.camera,
        status=JobSegmentRunImportStatus.LOADING
    )
    await session.commit()


    unique_folder_name = str(uuid4())
    dest_path = DATA_DIR / unique_folder_name
    try:
        # Download job run info from minio
        job_segment_run = await job_segment_run_service.get_job_segment_run(
            job_run_num=job_segment_run_import.job_run_num,
            job_def_id=job_segment_run_import.job_def_id,
            route_id=job_segment_run_import.route_id,
            segment_id=job_segment_run_import.segment_id,
            camera=job_segment_run_import.camera,
        )
        if not job_segment_run:
            raise JobSegmentRunNotFoundError(
                job_run_num=job_segment_run_import.job_run_num,
                job_def_id=job_segment_run_import.job_def_id,
                route_id=job_segment_run_import.route_id,
                segment_id=job_segment_run_import.segment_id,
            )

        job_segment_run_dir = await job_segment_artifact_downloader_service.download_job_segment_run_artifacts(
            job_segment_run=job_segment_run,
            dest_path=dest_path
        )

        # Create task in cvat
        task_name = f"{job_segment_run_import.route_id}-{job_segment_run_import.segment_id}-{job_segment_run_import.job_def_id}-{job_segment_run_import.job_run_num}-export"
        new_task = cvat_service.create_new_annotated_task_for_job_segment_run_dir(
            job_segment_run_dir=job_segment_run_dir,
            task_name=task_name
        )

        task_id = new_task.id
        job_id = new_task.get_jobs()[0].id

        job_segment_run_import.task_url = get_task_url(task_id=task_id, job_id=job_id)
        job_segment_run_import.task_id = task_id


        await job_segment_run_import_service.set_status(
            job_run_num=job_segment_run_import.job_run_num,
            job_def_id=job_segment_run_import.job_def_id,
            route_id=job_segment_run_import.route_id,
            segment_id=job_segment_run_import.segment_id,
            camera=job_segment_run_import.camera,
            status=JobSegmentRunImportStatus.LOADED
        )
        await session.commit()
    except Exception as e:
        logging.error(f"Job loading failed: {job_segment_run_import}", e)
        await job_segment_run_import_service.set_error(
            job_segment_run_import=job_segment_run_import,
            error_message=f"Failed while loading into cvat: {type(e)}, {e}"
        )
        await session.commit()
    finally:
        shutil.rmtree(dest_path)

async def _process_removal_job(
    job_segment_run_import:JobSegmentRunImport,
    job_segment_run_import_service:JobSegmentRunImportService,
    cvat_service:CVATService,
    session: AsyncSession
):
    logging.info(f"Processing loading job {job_segment_run_import}")
    await job_segment_run_import_service.set_status(
        job_run_num=job_segment_run_import.job_run_num,
        job_def_id=job_segment_run_import.job_def_id,
        route_id=job_segment_run_import.route_id,
        segment_id=job_segment_run_import.segment_id,
        camera=job_segment_run_import.camera,
        status=JobSegmentRunImportStatus.REMOVING
    )
    await session.commit()


    try:
        # Try to remove job from CVAT
        if not job_segment_run_import.task_id:
            raise ValueError(f"Job segment run import does not have a task id: {job_segment_run_import}")

        cvat_service.delete_task(
            task_id=job_segment_run_import.task_id
        )

        await job_segment_run_import_service.set_status(
            job_run_num=job_segment_run_import.job_run_num,
            job_def_id=job_segment_run_import.job_def_id,
            route_id=job_segment_run_import.route_id,
            segment_id=job_segment_run_import.segment_id,
            camera=job_segment_run_import.camera,
            status=JobSegmentRunImportStatus.REMOVED
        )
        await session.commit()
    except Exception as e:
        logging.error(f"Job loading failed: {job_segment_run_import}", e)
        await job_segment_run_import_service.set_error(
            job_segment_run_import=job_segment_run_import,
            error_message=f"Failed while removing from cvat: {type(e)}, {e}"
        )
        await session.commit()

async def _process_job(
    job_segment_run_import:JobSegmentRunImport,
    job_segment_run_import_service:JobSegmentRunImportService,
    job_segment_run_service:JobSegmentRunService,
    job_segment_artifact_downloader_service: JobSegmentArtifactDownloaderService,
    cvat_service:CVATService,
    session: AsyncSession
):
    logging.info(f"Processing {job_segment_run_import}")
    if job_segment_run_import.status == JobSegmentRunImportStatus.QUEUED_FOR_LOADING:
        await _process_loading_job(
            job_segment_run_import=job_segment_run_import,
            job_segment_run_import_service=job_segment_run_import_service,
            job_segment_run_service=job_segment_run_service,
            job_segment_artifact_downloader_service=job_segment_artifact_downloader_service,
            cvat_service=cvat_service,
            session=session
        )
    elif job_segment_run_import.status == JobSegmentRunImportStatus.QUEUED_FOR_REMOVAL:
        await _process_removal_job(
            job_segment_run_import=job_segment_run_import,
            job_segment_run_import_service=job_segment_run_import_service,
            cvat_service=cvat_service,
            session=session
        )
    else:
        raise ValueError(f"Invalid status on {job_segment_run_import}")

async def main():
    logger.info("Starting worker")
    
    engine = create_async_engine(
        url=build_database_url(),
        pool_pre_ping=True
    )
    SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

    stop_event = asyncio.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig=sig, callback=stop_event.set)

    try:
        async with SessionLocal() as session:
            job_segment_run_import_repository = JobSegmentRunImportRepository(session=session)
            job_segment_run_import_service = JobSegmentRunImportService(job_segment_run_import_repository)
            frame_repository = FrameRepository(session=session)
            frame_service = FrameService(frame_repository)
            artifact_repository = ArtifactRepository(session=session)
            artifact_service = ArtifactService(artifact_repository)
            cvat_service = CVATService()
            job_segment_run_repository = JobSegmentRunRepository(session=session)
            job_segment_run_service = JobSegmentRunService(job_segment_run_repository)
            minio_service = MinioService()
            segment_repository = SegmentRepository(session)
            segment_service = SegmentService(segment_repository)
            frame_artifact_repository = FrameArtifactRepository(session=session)
            frame_artifact_service = FrameArtifactService(frame_artifact_repository)
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
            job_segment_artifact_downloader_service = JobSegmentArtifactDownloaderService(
                job_segment_run_service=job_segment_run_service,
                artifact_service=artifact_service,
                segment_artifact_download_service=segment_artifact_download_service,
                segment_service=segment_service,
                minio_service=minio_service
            )



            await _mark_stale_running_jobs_as_failed(
                job_segment_run_import_service=job_segment_run_import_service
            )
            await session.commit()

            while not stop_event.is_set():
                logging.info("Checking for queues job segment run imports")
                job_segment_run_import = await job_segment_run_import_service.get_next_by_statuses(statuses=[JobSegmentRunImportStatus.QUEUED_FOR_LOADING, JobSegmentRunImportStatus.QUEUED_FOR_REMOVAL])

                if job_segment_run_import is None:
                    await session.rollback()
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                await _process_job(
                    job_segment_run_import=job_segment_run_import,
                    job_segment_run_import_service=job_segment_run_import_service,
                    job_segment_run_service=job_segment_run_service,
                    job_segment_artifact_downloader_service=job_segment_artifact_downloader_service,
                    cvat_service=cvat_service,
                    session=session,
                )






    finally:
        executor.shutdown(wait=False)
        await engine.dispose()
        logger.info("Worker Shutdown Complete")


if __name__ == "__main__":
    asyncio.run(main())
