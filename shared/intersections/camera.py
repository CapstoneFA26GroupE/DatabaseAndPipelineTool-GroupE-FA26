import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TRAFFIC_LIGHT_LABELS = {"traffic light", "traffic_light", "trafficlight"}
STOP_SIGN_LABELS = {"stop sign", "stop_sign", "stopsign"}


@dataclass
class CameraObservation:
    # what the detector saw in one frame
    traffic_lights: int
    stop_signs: int
    max_light_score: float


class TrafficLightDetector:
    # this runs the project's object detection model (coco classes) and only keeps traffic lights and stop signs

    def __init__(self, model_name: str, min_score: float, min_light_height: float) -> None:
        # torch / transformers are imported here so the rest of the classifier works without them
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        self._torch = torch
        self.min_score = min_score
        self.min_light_height = min_light_height
        logger.info("Loading camera check model %s", model_name)
        self.processor = AutoImageProcessor.from_pretrained(model_name)
        self.model = AutoModelForObjectDetection.from_pretrained(model_name)
        self.model.eval()

        labels = {int(i): str(name).strip().lower() for i, name in self.model.config.id2label.items()}
        self.light_ids = {i for i, name in labels.items() if name in TRAFFIC_LIGHT_LABELS}
        self.stop_ids = {i for i, name in labels.items() if name in STOP_SIGN_LABELS}
        if not self.light_ids:
            raise ValueError(f"Model {model_name} has no 'traffic light' class, so it can't be used for the camera check")

    def observe(self, image_path: Path) -> CameraObservation:
        # this detects traffic lights and stop signs in one image
        from PIL import Image

        torch = self._torch
        with Image.open(image_path) as raw:
            image = raw.convert("RGB")
        width, height = image.size
        with torch.no_grad():
            inputs = self.processor(images=[image], return_tensors="pt")
            outputs = self.model(**inputs)
            results = self.processor.post_process_object_detection(
                outputs=outputs,
                threshold=self.min_score,
                target_sizes=torch.tensor([[height, width]]),
            )[0]

        lights = 0
        stops = 0
        max_light_score = 0.0
        for box, label, score in zip(results["boxes"], results["labels"], results["scores"]):
            label_id = int(label.item())
            box_height = float(box[3].item() - box[1].item())
            if label_id in self.light_ids:
                # this ignores tiny lights, which usually belong to an intersection further down the road
                if box_height >= self.min_light_height * height:
                    lights += 1
                    max_light_score = max(max_light_score, float(score.item()))
            elif label_id in self.stop_ids:
                stops += 1
        return CameraObservation(traffic_lights=lights, stop_signs=stops, max_light_score=round(max_light_score, 3))
