from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.engine import AsyncEngine

from db.url import build_database_url
from services.errors import (
    CVATActiveError,
    DatasetExportDeletionConflictError,
    DatasetExportNotFoundError,
    DatasetExportValidationError,
    JobRunCancelError,
    JobRunNotFoundError,
    JobRunRequeueError,
    JobRunningError,
    JobSegmentRunImportDeleteError,
    RouteAlreadyExistsError,
    RouteDeleteError,
    RouteNotFoundError,
    RouteNotReadyForJobRunError,
)

from api.routers.dataset_exports import dataset_exports_router
from api.routers.routes import routes_router
from api.routers.segments import segments_router
from api.routers.job_runs import job_runs_router
from api.routers.job_definitions import job_definitions_router
from api.routers.job_segment_run import job_segment_run_router
from api.routers.cvat import cvat_router

FRONTEND_URL = os.getenv("FRONTEND_URL")
if not FRONTEND_URL:
    raise ValueError("FRONTEND_URL can not be empty")

@asynccontextmanager
async def lifespan(app: FastAPI):
    
    engine: AsyncEngine = create_async_engine(build_database_url(), pool_pre_ping=True)
    session_local: async_sessionmaker[AsyncSession] = async_sessionmaker(bind=engine, expire_on_commit=False)

    app.state.engine = engine
    app.state.session_local = session_local 

    try:
        yield
    finally:
        await engine.dispose()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health-check")
async def health_check() -> dict[str, str]:
    return {"status": "alive"}


@app.exception_handler(RouteAlreadyExistsError)
async def handle_route_exists_error(
    _: Request,
    exc: RouteAlreadyExistsError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


@app.exception_handler(RouteNotFoundError)
async def handle_route_not_found_error(
    _: Request,
    exc: RouteNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


@app.exception_handler(RouteNotReadyForJobRunError)
async def handle_route_not_ready_for_job_run_error(
    _: Request,
    exc: RouteNotReadyForJobRunError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


@app.exception_handler(DatasetExportNotFoundError)
async def handle_dataset_export_not_found_error(
    _: Request,
    exc: DatasetExportNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


@app.exception_handler(DatasetExportValidationError)
async def handle_dataset_export_validation_error(
    _: Request,
    exc: DatasetExportValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


@app.exception_handler(DatasetExportDeletionConflictError)
async def handle_dataset_export_deletion_conflict_error(
    _: Request,
    exc: DatasetExportDeletionConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )

@app.exception_handler(RouteDeleteError)
async def handle_route_delete_error(
        _: Request,
        exec: RouteDeleteError
    ):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exec)})

@app.exception_handler(JobSegmentRunImportDeleteError)
async def handle_job_segment_run_import_delete_error(
        _: Request,
        exec: RouteDeleteError
):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exec)})

@app.exception_handler(JobRunNotFoundError)
async def handle_job_run_not_found_error(
        _: Request,
        exec: JobRunNotFoundError
):
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exec)})

@app.exception_handler(JobRunCancelError)
async def handle_job_run_cancel_error(
        _: Request,
        exec: JobRunCancelError
):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exec)})

@app.exception_handler(JobRunRequeueError)
async def handle_job_run_requeue_error(
        _: Request,
        exec: JobRunRequeueError
):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exec)})

@app.exception_handler(JobRunningError)
async def handle_job_running_error(
        _: Request,
        exec: RouteDeleteError
):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exec)})

@app.exception_handler(CVATActiveError)
async def handle_cvat_active_error(
        _: Request,
        exec: CVATActiveError
):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exec)})


app.include_router(router=routes_router)
app.include_router(router=segments_router)
app.include_router(router=job_runs_router)
app.include_router(router=job_definitions_router)
app.include_router(router=job_segment_run_router)
app.include_router(router=dataset_exports_router)
app.include_router(router=cvat_router)
