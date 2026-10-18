"""YOLOv8 person detection, shared by the local and cloud pipelines.

The model is loaded lazily on first use, so importing this module never loads
weights or touches the network/filesystem.
"""

YOLO_MODEL = "yolov8n.pt"
YOLO_IMGSZ = 1280
YOLO_CONF = 0.30
YOLO_IOU = 0.50
YOLO_MAX_DET = 300


class PersonDetector:
    """YOLOv8n person-only detector (COCO class 0)."""

    def __init__(self, model_path=YOLO_MODEL):
        self.model_path = model_path
        self._model = None

    def _load(self):
        if self._model is None:
            from ultralytics import YOLO  # deferred: model loading is heavy

            self._model = YOLO(self.model_path)
        return self._model

    def count_persons(self, frame):
        """Detect persons in ``frame``; return ``(count, annotated_bgr)``."""
        result = self._load().predict(
            source=frame,
            imgsz=YOLO_IMGSZ,
            conf=YOLO_CONF,
            iou=YOLO_IOU,
            classes=[0],
            max_det=YOLO_MAX_DET,
            verbose=False,
        )[0]
        boxes = result.boxes
        count = 0 if boxes is None else len(boxes)
        return count, result.plot()
