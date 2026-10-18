# scripts/

CLI helpers for the SLS pipeline.

- `download_video.py` — downloads a YouTube (or any yt-dlp-supported) video as an H.264/MP4 clip
  for OpenCV-friendly playback. CLI:
  `python scripts/download_video.py <URL> [-o OUTPUT] [--name NAME]`. Prefers the `yt_dlp`
  Python API, falling back to the `yt-dlp` executable; output defaults to
  `data/<slugified-title>.mp4`.
- `build_architecture_diagram.py` — renders the Part 3 architecture diagram with the `diagrams`
  package (Graphviz backend) to `docs/architecture.png`. Run with
  `venv/bin/python scripts/build_architecture_diagram.py`; needs the `docs` extra
  (`pip install -e ".[docs]"`) and the Graphviz `dot` binary.
- `preview_web.py` — serves `web/` locally with generated dummy `database.csv` + a frame image for
  offline layout checks, without touching Azure or the real `web/` files (a temp copy). Run
  `venv/bin/python scripts/preview_web.py --port 8137` and open `http://127.0.0.1:8137/`. Optional
  `--debug` injects a yellow panel/canvas/image width readout (and page-title mirror) at the foot;
  `--resize-test` simulates a runtime container resize (used to verify the chart re-fits via
  `ResizeObserver`).