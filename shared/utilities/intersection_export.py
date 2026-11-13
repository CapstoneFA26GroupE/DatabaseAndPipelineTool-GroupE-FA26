import json
import logging
from pathlib import Path

from intersections.labels import DISPLAY_NAMES

logger = logging.getLogger(__name__)

LABELS_FILE_NAME = "intersection_labels.json"


def _frame_id_from_file_name(file_name: str) -> int | None:
    stem = Path(file_name).stem
    return int(stem) if stem.isdigit() else None


def filter_job_outputs_to_frames(export_root: Path, allowed: dict[int, set[int]]) -> int:
    # this removes frames that were filtered out of the export from the job output files,
    # so coco annotations and depth indexes only point at images that are actually in the zip.
    # returns how many image entries were removed
    removed = 0
    for path in (export_root / "job_runs").rglob("data.json"):
        try:
            segment_id = int(path.parent.name)
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            logger.warning("Skipping unreadable job output %s", path)
            continue
        keep = allowed.get(segment_id, set())
        images = data.get("images")
        if not isinstance(images, list):
            continue

        if data.get("kind") == "monocular_depth":
            # this block handles the depth index: each image entry has its frame_id
            kept = [image for image in images if image.get("frame_id") in keep]
            removed += len(images) - len(kept)
            data["images"] = kept
        elif "annotations" in data:
            # this block handles coco detection files: drop the images and their annotations
            kept_ids = set()
            kept = []
            for image in images:
                frame_id = _frame_id_from_file_name(str(image.get("file_name", "")))
                if frame_id is None or frame_id in keep:
                    kept.append(image)
                    kept_ids.add(image.get("id"))
            removed += len(images) - len(kept)
            data["images"] = kept
            data["annotations"] = [a for a in data.get("annotations", []) if a.get("image_id") in kept_ids]
        else:
            continue
        path.write_text(json.dumps(data), encoding="utf-8")
    return removed


def write_intersection_labels(export_root: Path, labels: dict[int, dict[int, str]]) -> Path:
    # this writes every frame's intersection label into the export so training code can filter by it
    path = export_root / LABELS_FILE_NAME
    payload = {
        "description": "intersection label of every frame, by segment_id then frame_id",
        "label_names": DISPLAY_NAMES,
        "segments": {
            str(segment_id): {str(frame_id): label for frame_id, label in sorted(frames.items())}
            for segment_id, frames in sorted(labels.items())
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
