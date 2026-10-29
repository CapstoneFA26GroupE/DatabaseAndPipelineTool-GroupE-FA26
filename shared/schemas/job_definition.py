from datetime import datetime

from pydantic import BaseModel, ConfigDict

from db.enums import JobType


class CreateJobDefinitionRequest(BaseModel):
    type: JobType
    implementation_key: str
    name: str
    config: dict
    description: str | None = None


class JobDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_def_id: int
    type: JobType
    implementation_key: str
    name: str
    description: str | None
    config: dict
    created_at: datetime
