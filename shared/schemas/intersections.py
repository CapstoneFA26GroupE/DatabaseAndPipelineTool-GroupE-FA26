from datetime import datetime
from typing import Any

from pydantic import BaseModel


class IntersectionSegmentCounts(BaseModel):
    segment_id: int
    # frames per label, e.g. {"signalized_intersection": 120, "non_intersection": 1080}
    counts: dict[str, int]


class IntersectionCameraSummary(BaseModel):
    enabled: bool = False
    sampled_frames: int = 0
    checked_intersections: int = 0
    error: str | None = None


class IntersectionSummaryResponse(BaseModel):
    route_id: str
    # waiting_for_upload, pending, running, done or failed
    status: str
    version: int | None = None
    error: str | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    counts: dict[str, int] = {}
    segments: list[IntersectionSegmentCounts] = []
    frames_total: int = 0
    frames_with_gps: int = 0
    intersections_passed: int = 0
    signalized_intersections: int = 0
    camera: IntersectionCameraSummary = IntersectionCameraSummary()
    # label value -> readable name
    labels: dict[str, str] = {}


class IntersectionFrameResponse(BaseModel):
    segment_id: int
    frame_id: int
    intersection_type: str
    intersection_details: dict[str, Any] | None = None
