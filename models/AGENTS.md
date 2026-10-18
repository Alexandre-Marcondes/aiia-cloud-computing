# models/

Model weights — not source.

- `yolov8n.pt` — YOLOv8 nano (COCO), ~6.5 MB, used by `src/detection.py` (`PersonDetector`).

Weights are excluded from version control (`*.pt` in `.gitignore`). Ultralytics downloads
`yolov8n.pt` by name into the working directory (the repo root) on first use; this directory only
documents them.
