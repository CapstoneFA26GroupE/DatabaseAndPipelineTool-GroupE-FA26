import os
from dataclasses import dataclass

# the label values stored on frames.intersection_type
SIGNALIZED = "signalized_intersection"
UNSIGNALIZED = "unsignalized_intersection"
NON_INTERSECTION = "non_intersection"
UNKNOWN = "unknown"

# labels a user can filter or export by (unknown means the frame had no gps fix)
CLASSIFIED_TYPES = (SIGNALIZED, UNSIGNALIZED, NON_INTERSECTION)
ALL_TYPES = CLASSIFIED_TYPES + (UNKNOWN,)

# readable names, matching the wording in the feature request
DISPLAY_NAMES = {
    SIGNALIZED: "signalized intersection",
    UNSIGNALIZED: "unsignalized intersection",
    NON_INTERSECTION: "non-intersection",
    UNKNOWN: "unknown (no gps)",
}

# bump this when the rules change so already labeled routes get labeled again
CLASSIFIER_VERSION = 2

# where the label came from and how sure we are
SOURCE_MAP = "map"
SOURCE_CAMERA = "camera"
SOURCE_MAP_AND_CAMERA = "map+camera"
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"


def _env_float(name: str, default: float) -> float:
    # this reads a number setting from the environment, falling back to the default
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    # this reads a true/false setting from the environment
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ClassifierConfig:
    # a frame within this distance of an intersection center counts as "at the intersection"
    intersection_radius_m: float = 30.0
    # frames without their own gps reading borrow one from neighbours at most this many frames apart (20 fps -> 0.5 s)
    gps_max_gap_frames: int = 10
    # frames within this distance are used for the camera check (the approach to the intersection)
    approach_radius_m: float = 60.0
    # junction nodes closer than this are merged into one intersection (divided roads, wide junctions)
    junction_cluster_m: float = 25.0
    # a mapped traffic signal within this distance of the center makes the intersection signalized
    signal_search_m: float = 40.0
    # camera check settings
    camera_check: bool = True
    camera_model: str = "PekingU/rtdetr_v2_r50vd"
    camera_samples_per_intersection: int = 6
    camera_min_score: float = 0.6
    # how many sampled frames must show a traffic light before the camera says "signals here"
    camera_min_signal_frames: int = 2
    # a traffic light must be at least this tall (fraction of image height) to count, so lights at a far-away intersection don't count
    camera_min_light_height: float = 0.02
    # map data settings
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    # backup overpass servers, tried in order when the main one refuses or is overloaded
    overpass_fallback_urls: tuple[str, ...] = (
        "https://overpass.private.coffee/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    )
    map_tile_deg: float = 0.02
    map_cache_dir: str = "/app/osm_cache"
    map_cache_days: float = 30.0

    @classmethod
    def from_env(cls) -> "ClassifierConfig":
        # this builds the config from INTERSECTION_* environment variables so it can be tuned without code changes
        defaults = cls()
        return cls(
            intersection_radius_m=_env_float("INTERSECTION_RADIUS_M", defaults.intersection_radius_m),
            approach_radius_m=_env_float("INTERSECTION_APPROACH_M", defaults.approach_radius_m),
            junction_cluster_m=_env_float("INTERSECTION_CLUSTER_M", defaults.junction_cluster_m),
            signal_search_m=_env_float("INTERSECTION_SIGNAL_SEARCH_M", defaults.signal_search_m),
            camera_check=_env_bool("INTERSECTION_CAMERA_CHECK", defaults.camera_check),
            camera_model=os.environ.get("INTERSECTION_CAMERA_MODEL", defaults.camera_model),
            camera_samples_per_intersection=int(
                _env_float("INTERSECTION_CAMERA_SAMPLES", defaults.camera_samples_per_intersection)
            ),
            camera_min_score=_env_float("INTERSECTION_CAMERA_MIN_SCORE", defaults.camera_min_score),
            camera_min_signal_frames=int(
                _env_float("INTERSECTION_CAMERA_MIN_SIGNAL_FRAMES", defaults.camera_min_signal_frames)
            ),
            camera_min_light_height=_env_float("INTERSECTION_CAMERA_MIN_LIGHT_HEIGHT", defaults.camera_min_light_height),
            gps_max_gap_frames=int(_env_float("INTERSECTION_GPS_MAX_GAP_FRAMES", defaults.gps_max_gap_frames)),
            overpass_url=os.environ.get("OVERPASS_URL", defaults.overpass_url),
            overpass_fallback_urls=tuple(
                url.strip() for url in os.environ.get(
                    "OVERPASS_FALLBACK_URLS", ",".join(defaults.overpass_fallback_urls)
                ).split(",") if url.strip()
            ),
            map_tile_deg=_env_float("INTERSECTION_MAP_TILE_DEG", defaults.map_tile_deg),
            map_cache_dir=os.environ.get("OSM_CACHE_DIR", defaults.map_cache_dir),
            map_cache_days=_env_float("OSM_CACHE_DAYS", defaults.map_cache_days),
        )
