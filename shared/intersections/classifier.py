from dataclasses import dataclass, field
from typing import Any, Iterable

from intersections.geo import GridIndex, LocalProjection
from intersections.labels import (
    CONFIDENCE_HIGH,
    DISPLAY_NAMES,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    NON_INTERSECTION,
    SIGNALIZED,
    SOURCE_CAMERA,
    SOURCE_MAP,
    SOURCE_MAP_AND_CAMERA,
    UNKNOWN,
    UNSIGNALIZED,
    ClassifierConfig,
)
from intersections.osm import Intersection

# (segment_id, frame_id) identifies a moment in the route; both cameras share it
FrameKey = tuple[int, int]


@dataclass(frozen=True)
class FramePoint:
    segment_id: int
    frame_id: int
    position: tuple[float, float] | None  # (lat, lon), None when there was no gps fix
    gps_interpolated: bool = False  # true when the position was filled in from neighbouring frames

    @property
    def key(self) -> FrameKey:
        return (self.segment_id, self.frame_id)


@dataclass
class CameraEvidence:
    # what the camera check saw across the sampled frames of one intersection
    sampled: int = 0
    signal_frames: int = 0
    stop_frames: int = 0
    max_signal_score: float = 0.0


@dataclass(frozen=True)
class IntersectionDecision:
    label: str
    source: str
    confidence: str
    reason: str


@dataclass
class FrameLabel:
    label: str
    details: dict[str, Any] = field(default_factory=dict)


class IntersectionMatcher:
    # this finds the nearest intersection to a gps point quickly

    def __init__(self, intersections: list[Intersection], search_m: float) -> None:
        self.intersections = intersections
        if intersections:
            lat0 = sum(i.lat for i in intersections) / len(intersections)
            lon0 = sum(i.lon for i in intersections) / len(intersections)
        else:
            lat0, lon0 = 0.0, 0.0
        self.projection = LocalProjection(lat0, lon0)
        self._grid: GridIndex[Intersection] = GridIndex(cell_m=max(search_m, 10.0))
        for intersection in intersections:
            x, y = self.projection.to_xy(intersection.lat, intersection.lon)
            self._grid.insert(x, y, intersection)

    def nearest(self, position: tuple[float, float], radius_m: float) -> tuple[float, Intersection] | None:
        if not self.intersections:
            return None
        x, y = self.projection.to_xy(*position)
        found = self._grid.query_radius(x, y, radius_m)
        return found[0] if found else None


@dataclass
class IntersectionPass:
    # one time the car drives past an intersection: the frames near it, in driving order, with their distances
    intersection: Intersection
    frames: list[tuple[FramePoint, float]] = field(default_factory=list)

    @property
    def closest_index(self) -> int:
        return min(range(len(self.frames)), key=lambda i: self.frames[i][1])

    def approach(self) -> list[tuple[FramePoint, float]]:
        # frames up to and including the closest point (the car is driving towards it)
        return self.frames[: self.closest_index + 1]

    def departure(self) -> list[tuple[FramePoint, float]]:
        # frames after the closest point (the car is driving away)
        return self.frames[self.closest_index + 1:]


def find_passes(frames: Iterable[FramePoint], matcher: IntersectionMatcher, radius_m: float) -> list[IntersectionPass]:
    # this walks the route in driving order and splits it into passes: a run of frames whose nearest
    # intersection (within radius_m) is the same one. frames without gps don't break a pass
    passes: list[IntersectionPass] = []
    current: IntersectionPass | None = None
    for frame in sorted(frames, key=lambda f: f.key):
        if frame.position is None:
            continue
        match = matcher.nearest(frame.position, radius_m)
        if match is None:
            current = None
            continue
        distance, intersection = match
        if current is None or current.intersection.id != intersection.id:
            current = IntersectionPass(intersection)
            passes.append(current)
        current.frames.append((frame, distance))
    return passes


def select_camera_samples(
    frames: Iterable[FramePoint],
    matcher: IntersectionMatcher,
    config: ClassifierConfig,
) -> dict[str, list[FrameKey]]:
    # this picks a few evenly spaced frames from each intersection's approach to run the camera check on.
    # only frames while driving towards it count: once past it, its lights and signs are behind the car
    approach: dict[str, list[FrameKey]] = {}
    for found in find_passes(frames, matcher, config.approach_radius_m):
        approach.setdefault(found.intersection.id, []).extend(frame.key for frame, _ in found.approach())

    samples: dict[str, list[FrameKey]] = {}
    limit = max(config.camera_samples_per_intersection, 0)
    for intersection_id, keys in approach.items():
        keys.sort()
        if limit == 0:
            continue
        if len(keys) <= limit:
            samples[intersection_id] = keys
        else:
            step = (len(keys) - 1) / (limit - 1) if limit > 1 else 0
            samples[intersection_id] = sorted({keys[round(i * step)] for i in range(limit)})
    return samples


def decide_intersection(
    intersection: Intersection,
    evidence: CameraEvidence | None,
    config: ClassifierConfig,
) -> IntersectionDecision:
    # this combines the map and the camera check into one label for an intersection:
    # - a traffic signal in the map data makes it signalized (high confidence if the camera also saw lights)
    # - no signal in the map but lights clearly seen by the camera: signalized (the map is missing it)
    # - otherwise unsignalized (high confidence if the camera looked and saw no lights)
    camera_ran = evidence is not None and evidence.sampled > 0
    camera_signal = camera_ran and evidence.signal_frames >= config.camera_min_signal_frames

    if intersection.map_signalized:
        if camera_signal:
            return IntersectionDecision(SIGNALIZED, SOURCE_MAP_AND_CAMERA, CONFIDENCE_HIGH,
                                        "traffic signal in map data and traffic lights seen by camera")
        if camera_ran:
            return IntersectionDecision(SIGNALIZED, SOURCE_MAP, CONFIDENCE_MEDIUM,
                                        "traffic signal in map data; no traffic lights seen in sampled frames")
        return IntersectionDecision(SIGNALIZED, SOURCE_MAP, CONFIDENCE_MEDIUM, "traffic signal in map data")

    if camera_signal:
        return IntersectionDecision(SIGNALIZED, SOURCE_CAMERA, CONFIDENCE_MEDIUM,
                                    "traffic lights seen by camera; no traffic signal in map data")
    if camera_ran:
        reason = "no traffic signal in map data or camera"
        if evidence.stop_frames > 0 or "stop" in intersection.controls:
            reason += "; stop sign present"
        return IntersectionDecision(UNSIGNALIZED, SOURCE_MAP_AND_CAMERA, CONFIDENCE_HIGH, reason)
    return IntersectionDecision(UNSIGNALIZED, SOURCE_MAP, CONFIDENCE_MEDIUM, "no traffic signal in map data")


def classify_frames(
    frames: Iterable[FramePoint],
    intersections: list[Intersection],
    evidence_by_intersection: dict[str, CameraEvidence],
    config: ClassifierConfig,
) -> dict[FrameKey, FrameLabel]:
    # this labels every frame: near an intersection -> that intersection's label (while approaching or
    # crossing it), otherwise non-intersection, and unknown when the frame has no gps position
    matcher = IntersectionMatcher(intersections, config.intersection_radius_m)
    decisions = {
        i.id: decide_intersection(i, evidence_by_intersection.get(i.id), config) for i in intersections
    }

    # this block finds the frames where the car is already driving away from an intersection it passed
    leaving: dict[FrameKey, tuple[Intersection, float]] = {}
    for found in find_passes(frames, matcher, config.intersection_radius_m):
        closest = found.frames[found.closest_index][1]
        for frame, distance in found.departure():
            if distance > closest + config.departure_margin_m:
                leaving[frame.key] = (found.intersection, distance)

    labels: dict[FrameKey, FrameLabel] = {}
    for frame in frames:
        if frame.position is None:
            labels[frame.key] = FrameLabel(UNKNOWN, {"reason": "no gps position for this frame",
                                                     "confidence": CONFIDENCE_LOW})
            continue

        match = matcher.nearest(frame.position, config.intersection_radius_m)
        if match is None:
            labels[frame.key] = FrameLabel(NON_INTERSECTION, {"source": SOURCE_MAP, "confidence": CONFIDENCE_HIGH,
                                                              "reason": "no intersection within "
                                                              f"{config.intersection_radius_m:g} m"})
            if frame.gps_interpolated:
                labels[frame.key].details["gps"] = "interpolated"
            continue

        distance, intersection = match
        decision = decisions[intersection.id]
        if frame.key in leaving:
            # past the intersection and driving away: the camera no longer sees it, so not an intersection frame
            labels[frame.key] = FrameLabel(NON_INTERSECTION, {
                "source": SOURCE_MAP, "confidence": CONFIDENCE_HIGH,
                "reason": f"leaving a {DISPLAY_NAMES[decision.label].lower()} it already drove through "
                          f"({distance:.0f} m behind)",
                "departed_intersection_id": intersection.id,
                "distance_m": round(distance, 1),
            })
            if frame.gps_interpolated:
                labels[frame.key].details["gps"] = "interpolated"
            continue
        evidence = evidence_by_intersection.get(intersection.id)
        labels[frame.key] = FrameLabel(
            decision.label,
            {
                "intersection_id": intersection.id,
                "distance_m": round(distance, 1),
                "source": decision.source,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "map_signalized": intersection.map_signalized,
                "map_controls": intersection.controls,
                "road_types": intersection.road_types,
                "camera_sampled": evidence.sampled if evidence else 0,
                "camera_signal_frames": evidence.signal_frames if evidence else 0,
                "intersection_lat": round(intersection.lat, 6),
                "intersection_lon": round(intersection.lon, 6),
            },
        )
        if frame.gps_interpolated:
            labels[frame.key].details["gps"] = "interpolated"
    return labels


def count_labels(labels: Iterable[FrameLabel]) -> dict[str, int]:
    # this counts frames per label (used for the route summary)
    counts: dict[str, int] = {}
    for label in labels:
        counts[label.label] = counts.get(label.label, 0) + 1
    return counts
