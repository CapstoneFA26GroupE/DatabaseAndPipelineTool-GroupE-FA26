# tests that exports filtered by intersection label stay consistent (annotations only point at exported images)
import json

from utilities.intersection_export import filter_job_outputs_to_frames, write_intersection_labels


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_coco_and_depth_outputs_are_filtered_to_exported_frames(tmp_path):
    coco_path = tmp_path / "job_runs/front_regular/1/1/segments/3/data.json"
    _write(coco_path, {
        "images": [{"id": 1, "file_name": "10.png"}, {"id": 2, "file_name": "11.png"}, {"id": 3, "file_name": "12.png"}],
        "annotations": [{"id": 7, "image_id": 1}, {"id": 8, "image_id": 2}, {"id": 9, "image_id": 3}],
    })
    depth_path = tmp_path / "job_runs/front_regular/2/1/segments/3/data.json"
    _write(depth_path, {"kind": "monocular_depth", "images": [{"frame_id": 10}, {"frame_id": 11}]})

    removed = filter_job_outputs_to_frames(tmp_path, {3: {10, 12}})

    coco = json.loads(coco_path.read_text())
    assert [i["file_name"] for i in coco["images"]] == ["10.png", "12.png"]
    assert [a["image_id"] for a in coco["annotations"]] == [1, 3]
    assert json.loads(depth_path.read_text())["images"] == [{"frame_id": 10}]
    assert removed == 2


def test_segment_with_no_matching_frames_is_emptied(tmp_path):
    path = tmp_path / "job_runs/front_wide/1/1/segments/5/data.json"
    _write(path, {"images": [{"id": 1, "file_name": "1.png"}], "annotations": [{"id": 2, "image_id": 1}]})
    filter_job_outputs_to_frames(tmp_path, {3: {1}})
    assert json.loads(path.read_text()) == {"images": [], "annotations": []}


def test_labels_file(tmp_path):
    path = write_intersection_labels(tmp_path, {0: {2: "non_intersection", 1: "signalized_intersection"}})
    data = json.loads(path.read_text())
    assert data["segments"] == {"0": {"1": "signalized_intersection", "2": "non_intersection"}}
    assert data["label_names"]["signalized_intersection"] == "signalized intersection"
