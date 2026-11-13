from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from db.enums import CameraType, DatasetExportStatus


class DatasetExportJobRunSelection(BaseModel):
    job_def_id: int
    job_run_num: int
    camera: CameraType


class CreateDatasetExportRequest(BaseModel):
    route_id: str
    camera_views: list[CameraType]
    job_runs: list[DatasetExportJobRunSelection]
    # only export frames with these intersection labels, e.g. ["signalized_intersection"]; None exports every frame
    intersection_types: list[str] | None = None


class DatasetExportJobRunSelectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_def_id: int
    job_run_num: int
    camera: CameraType


class DatasetExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    export_id: int
    route_id: str
    camera_views: list[CameraType]
    status: DatasetExportStatus
    error: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    zip_artifact_id: UUID | None
    intersection_types: list[str] | None = None
    job_runs: list[DatasetExportJobRunSelectionResponse]
