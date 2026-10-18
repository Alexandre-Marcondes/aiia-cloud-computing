# src/

Python side of the SLS pipeline: frame capture + person counting. Local scripts (test/demo), a cloud
receiver for the Azure VM, and a serverless adapter (see [`../serverless/`](../serverless/)), all over
a set of reusable modules. Our code adapts the Teaching Team's provided sample process (see
`docs/AGENTS.md`).

## Scripts

- `local_test_platform.py` — Part 1 local demo on a **video file** only (deterministic testing). By
  default it plays the clip in real time (looping) and, every `--interval` s (default 5.0, float),
  runs the shared pipeline on the current frame; frames read between ticks are discarded and the last
  annotated frame stays in an OpenCV window (press `q` to stop). `--fast` seeks straight to each
  sample instead of waiting, for quick checks.
- `local_stream.py` — unified local runner and the Part 1 client. `--source` (default
  `data/people_walking.mp4`) selects either a **local video** — played in real time exactly like
  `local_test_platform.py`, and where `--fast` applies — or the **live SkylineWebcams HLS stream**
  via the aliases `live`/`salò`/`skyline` or a page URL; live mode reads the stream on a background
  thread. By default it processes locally; `--cloud-url` uploads each frame to `cloud_receiver.py`
  (Part 2), and `--blob-connection-string` uploads it to a storage account's `raw` container for the
  serverless function (Part 3, `--raw-container`); both skip local YOLO/CSV/chart. `--cameras N`
  (default 1) drives N pseudo-cameras `<base>-1`..`<base>-N` (base `--camera-id` or `cam`) from one
  local clip via the `multicam` scheduler — needs an upload target and a local video, so it rejects
  `--fast` and live sources; `--seconds` bounds the run and `--show-streams` shows a labelled mosaic.
  `--phase-offset S` (multi-camera) makes each successive camera sample the clip `S` seconds behind
  the previous, so the cameras show different points in time rather than the same frame.
  `--cameras 1` is the original single-camera path unchanged; `camera_ids(base, n)` builds the ids.
- `cloud_receiver.py` — Part 2 receiver, run on the Azure VM (see `deploy/`). A stdlib HTTP server
  that accepts raw-JPEG POSTs on `/frame`, runs `PersonDetector` on each, and appends the count +
  writes the annotated frame into the web document root; `/health` reports liveness. Responses carry
  `processing_ms` (decode + inference + write) for performance work. Camera-aware: the `X-Camera-Id`
  header's reserved `cam` (or none) is the legacy path; any other id writes `frames/<camera>.jpg`
  and its CSV row is camera-tagged. The single processing lock is deliberate (the Part 4.2
  bottleneck).
- `load_test.py` — Part 2.5 load generator/probe: sends synthetic (`--size`, reproducible noise) or
  `--image` JPEG frames to a receiver and reports round-trip and server-side latency statistics.
- `measure_serverless.py` — Part 3.6 end-to-end probe: uploads frames one at a time to the `raw`
  container and measures upload→visible latency (until `$web/database.csv`'s ETag changes) plus the
  raw-blob deletion latency and CSV rows added; reports the same latency statistics as `load_test`.
  See `docs/performance.md`.

The local scripts write `data/database.csv` (`Timestamp,Person_Count`, header once),
`data/processed_frame.jpg` (annotated), and `data/plot.png` (chart). In video mode an OpenCV window
previews the annotated frame; `--no-display` disables the GUI windows and `--max-samples` bounds the
run.

## Shared modules

Imported as top-level modules (`src/` is on `sys.path` via the editable install and when running
`python src/<script>.py`):

- `sources.py` — frame sources: `VideoSampler` (seek/loop a local file), `VideoPlayer` (sequential,
  real-time-capable playback of a local file), `FrameGrabber` (threaded HLS reader with
  `read(last_seq, timeout)`), `resolve_source` (`--source` → live page URL vs local path),
  `get_stream_url`, `DEFAULT_PAGE_URL`, `LIVE_ALIASES`, `VideoError`.
- `detection.py` — `PersonDetector`: YOLOv8n person-only detection (class 0, `imgsz=1280`,
  `conf=0.30`, `iou=0.50`), weights loaded lazily on first use.
- `vision.py` — `analyze_people`: Azure AI Vision (Image Analysis 4.0 `people`) client returning the
  per-person bounding boxes; the serverless counterpart of `detection.py`. Drops boxes below
  `DEFAULT_MIN_CONFIDENCE` (0.30, mirroring YOLO's `conf`) because the feature emits many
  low-confidence false positives; `min_confidence=0.0` returns the raw list.
- `stats.py` — `PersonStats`: running samples / total / mean / min / max.
- `csv_log.py` — the shared CSV/timestamp contract: `CSV_HEADER` (`Timestamp,Person_Count`) and
  `CSV_HEADER_V2` (`Timestamp,Camera,Person_Count`), `now_timestamp`, `format_row`, `append_row`
  (bytes, for blob storage), and `log_sample` (append to a file). `camera=None` keeps the legacy
  schema; the header is picked from the row's field count. **A schema switch rotates the file**: when
  the incoming row's column count differs from the file's header (e.g. a streamer restart with a
  different camera count), `log_sample`/`append_row` reset it to a fresh header + row, so a camera
  change never leaves a database mixing legacy and multi-camera rows (and heals an already-mixed one).
- `plotting.py` — `PlotDisplay`: live/saved matplotlib chart, headless-safe (Agg fallback).
- `render.py` — `draw_boxes`: draw person bounding boxes onto a JPEG (Pillow); used by the
  serverless function.
- `pipeline.py` — `process_sample`: detect → stats → CSV → annotated frame → chart → log line;
  returns `(count, annotated)`; the per-sample unit reused by the local scripts and the receiver.
  An optional `camera` tags the CSV row and the annotated frame for multi-camera runs.
- `runner.py` — the sampling loops shared by the local scripts: `run_video` (real-time emulation, or
  `--fast` seek, of a local file), `run_live` (sample the latest `FrameGrabber` frame each interval),
  and `make_local_sink` (the local `on_frame` sink; cloud upload uses `transport.make_cloud_sink`).
- `multicam.py` — the Part 4 multi-camera scheduler: `phase_offset` (evenly staggered startup),
  `frame_offset` (per-camera clip-position lag), `SharedVideoSource` (one real-time decoder thread all
  cameras read via `latest_frame`; when given a `keep_seconds` window it also keeps a bounded JPEG
  time-shift buffer read via `frame_ago(seconds)`), `CameraWorker` (a thread per camera ticking on a
  phase-offset schedule and handing the shared — or time-shifted — frame to its sink), `run_cameras`
  (drives the fleet, prints per-camera totals), and `compose_grid` (the display-only mosaic for
  `--show-streams`). Keeps local decode to a single decoder so a sweep measures the server, not the
  sender; the buffer's frame rate (`BUFFER_FPS`) and size (`MAX_BUFFER_BYTES`) are capped so a
  `--phase-offset` run stays cheap regardless of the clip's resolution.
- `transport.py` — frame-upload protocol shared by the sender and receiver: `encode_jpeg` /
  `decode_jpeg`, `post_frame`, `make_cloud_sink`, `normalize_endpoint`, `FRAME_PATH`.
- `blob_transport.py` — Azure Blob transport for Part 3: sender `make_blob_sink` /
  `make_blob_sink_from_connection_string` / `blob_name`, and function side `upload_jpeg` /
  `append_csv` (ETag retry), `blob_name_in_container`, and the camera contract (`RESERVED_CAMERA`,
  `FRAMES_PREFIX`, `camera_from_name`, `camera_frame_name`); `azure-storage-blob` is imported lazily.
- `paths.py` — `REPO_ROOT`, `resolve_path` (relative → repo-root anchored), `ensure_parent`.
