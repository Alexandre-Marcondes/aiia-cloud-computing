# aiia-cloud-computing

Coursework for **Arquitecturas e Infraestructuras para Inteligencia Artificial** — *Practice 1:
Cloud Computing Services* (University of Alicante, Master's in AI).

The task is to build a **Smart Lighting System (SLS)** presence sensor for a Smart City: a public
fixed webcam acts as the sensor, frames are processed to count people, and the counts are logged
and graphed over time. Later parts move the same pipeline to the cloud (Azure VM, Azure Functions)
and serve a static page from an Azure storage container.

Full brief: [`docs/Practice1.pdf`](docs/Practice1.pdf). The remaining course material lives in
[`docs/`](docs/).

## Pipeline

```
public webcam (HLS) → frame capture → YOLOv8 person detection → CSV log → web chart
                                       (class 0, imgsz=1280)
```

The source camera is a fixed SkylineWebcams stream (Salò, Lake Garda). Person detection uses the
pretrained **YOLOv8n** model via [Ultralytics](https://ultralytics.com/yolov8). For deterministic
local testing the same pipeline can read a downloaded clip instead of the live stream — see
[Testing with a local video](#testing-with-a-local-video).

## Assignment parts

1. **Local** — capture a frame every 5 s, count people with YOLOv8, save counts to CSV, graph them.
2. **Cloud VM** — ship frames to an Azure `Standard_B2ats_v2` VM, run detection there, host a webpage on
   its public IP; measure efficiency, CPU/memory, bandwidth, cost, response time.
3. **Serverless** — upload frames to a raw blob container every 0.5 s; a blob-trigger Azure Function
   processes them (optionally via Azure Computer Vision tagging); a static site in a separate
   container shows the results.
4. **Multi-camera** — scale to several cameras sending 1 frame / 5 s each, and find the VM's and the
   serverless app's processing limits.

Deliverable: a PDF project report (steps, problems, design decisions, conclusions).

## Navigating the project

| Path | Contents |
| --- | --- |
| `docs/` | Course PDFs, the Part 3 design doc (`architecture.md`), the performance reference (`performance.md`), committed sweep captures (`sweeps/`), and the measurement reports (`measurements/`) |
| `src/` | Python pipeline — frame capture + person detection (local, VM receiver, serverless adapter) |
| `scripts/` | CLI helpers — `download_video.py`, the architecture-diagram builder, and an offline web preview |
| `deploy/` | Azure deployment — VM setup/sync/measure + the Part 3 deploy and Part 4 sweep scripts |
| `web/` | Static frontend — person-count chart + histogram + processing-time chart + latest frame (single- and multi-camera) |
| `models/` | Documents the YOLO weights (downloaded to the repo root on first use; not committed) |
| `data/` | Local runtime output (`database.csv`, annotated frame, chart, downloaded clips; gitignored) |
| `tests/` | Offline unit tests (`pytest`; also runnable via `python -m unittest discover -s tests`) |

## Testing with a local video

Live public webcams are unreliable for development: they can be offline, dark, or — at quiet hours —
show nobody at all, so the detector has nothing to find and results are not repeatable. To make
testing deterministic we use a downloaded clip as the frame source.

The reference clip is *People Walking Past the Camera* (free stock footage, 46 s, 1920×1080):
<https://www.youtube.com/watch?v=3FXUw98rrUY>. It has a continuous, well-lit flow of people who are
large in frame, so YOLOv8n detects them reliably — sampling every second, the count ran from 1 to 15
and **no frame was empty**, which makes it a good stand-in for a busy surveillance camera.

Download it (H.264/MP4, so OpenCV can always decode it). The downloader needs `yt-dlp` — either the
Python module (`pip install -e ".[utils]"`) or the `yt-dlp` executable on `PATH`:

```sh
python scripts/download_video.py "https://www.youtube.com/watch?v=3FXUw98rrUY"
# → data/<slugified-title>.mp4 (e.g. data/people_walking.mp4);
#   use -o PATH or --name NAME to control where it lands
```

The clip is written to `data/` and is gitignored. Both local scripts use it as the frame source and,
by default, play it in **real time** — like the live feed, looping at the end — running detection
every 5 s and showing the annotated frame in a window (press `q` to stop):

```sh
python src/local_test_platform.py            # Part 1 video-only demo, 1 sample / 5 s
python src/local_stream.py                   # the same, via the unified runner
python src/local_test_platform.py --fast     # seek straight to each sample (quick checks)
python src/local_stream.py --no-display --max-samples 3   # headless quick run
```

Point the unified `src/local_stream.py` at the actual camera with `--source live` (the fixed Salò
stream) — or any other SkylineWebcams page URL:

```sh
python src/local_stream.py --source live     # live SkylineWebcams HLS stream
```

This local-video run is the Part 1 (local) demo: the whole capture → YOLO → CSV → chart path on a
single machine. Both scripts are thin over the reusable modules in `src/` (`sources`, `runner`,
`transport`, `detection`, `stats`, `csv_log`, `plotting`, `pipeline`, `paths`) — see
[`src/AGENTS.md`](src/AGENTS.md). To offload detection to the cloud, `local_stream.py` can upload
frames instead of processing them with `--cloud-url` — see
[Offloading to the cloud VM](#offloading-to-the-cloud-vm-part-2).

## Interesting camera sources

`--source` accepts any SkylineWebcams page URL (the scraper resolves its HLS playlist), so the
sensor can point at different scenes. A few worth keeping:

| Camera | URL | Why it's useful |
| --- | --- | --- |
| Salò, Lake Garda (default) | <https://www.skylinewebcams.com/en/webcam/italia/lombardia/brescia/salo-lago-di-garda.html> | the default lakefront promenade camera |
| Playa de los Cristianos, Tenerife | <https://www.skylinewebcams.com/en/webcam/espana/canarias/santa-cruz-de-tenerife/playa-los-cristianos.html> | a busy beach — a crowded frame (≈90–130 people) stresses the detector and the histogram |
| St Julian's, Malta | <https://www.skylinewebcams.com/en/webcam/malta/malta/st-julians/st-julians.html> | a waterfront with **cars** in frame — useful for the additional tasks |

```sh
python src/local_stream.py --source "<url>"           # locally (Part 1)
bash deploy/stream_vm.sh --source "<url>"             # through the VM receiver (Part 2)
bash deploy/stream_serverless.sh --source "<url>"     # through the raw container → Function (Part 3)
```

## Offloading to the cloud VM (Part 2)

Part 2 moves detection to an Azure VM. `src/cloud_receiver.py` runs there as a service
(`deploy/sls-receiver.service`): it accepts raw-JPEG POSTs on `/frame`, counts people with the same
YOLOv8 detector, and writes `database.csv` + `processed_frame.jpg` into the Apache document root. The
static `web/` page is served from that same root, so the frontend just polls those two files — no
API, database, or websocket involved. The page shows the counts time-series, a **person-count
histogram** (Task 2.4), the per-frame processing-time chart, and the latest annotated frame.

On the local machine, point the streamer at the receiver instead of processing locally. The receiver
listens on port 8000, which the VM's Azure NSG does **not** expose, so bridge to it over the
**already-open SSH port** rather than adding a firewall rule (see *Why a tunnel* below):

```sh
# terminal 1 — keep open: forwards localhost:8000 to the VM's receiver over SSH
ssh -i ~/.ssh/<vm-ssh-key> -N -L 8000:127.0.0.1:8000 <vm-ssh-user>@<vm-public-ip>

# terminal 2 — send frames (default source is the local clip, one frame every 5 s)
python src/local_stream.py --cloud-url http://127.0.0.1:8000
python src/local_stream.py --cloud-url http://127.0.0.1:8000 --fast --max-samples 5   # quick demo
```

Or do both steps in one command — `deploy/stream_vm.sh` opens the tunnel, streams, and tears the
tunnel down when it exits (Ctrl-C); it reuses a forward that is already open:

```sh
bash deploy/stream_vm.sh                              # continuous, one frame every 5 s
bash deploy/stream_vm.sh --fast --max-samples 5       # quick demo
bash deploy/stream_vm.sh --cameras 3                  # 3 pseudo-cameras
```

Then open `http://<vm-public-ip>/`: the annotated frame, the counts, and a green `Last update:` line
(red once the streamer stops).

> **Why a tunnel?** Task 2.4's public-IP requirement covers the **web page** (:80, already open); it
> does not require the frame-upload endpoint to be public. Bridging the upload over the open SSH port
> needs no Azure networking changes. To send straight to the public IP instead, open TCP `8000` in the
> VM's NSG (Portal → VM → Networking → Add inbound port rule) and use
> `--cloud-url http://<vm-public-ip>:8000`.

Push the code to the VM with `deploy/sync.sh` (rsync over SSH — no git credentials needed on the VM;
`--web` also publishes the frontend to `/var/www/html`), then provision the VM by running
`bash deploy/setup_vm.sh` there (swap + packages + venv + CPU PyTorch, idempotent). Installing the
systemd service (`deploy/sls-receiver.service`) is a one-time step described in
[`deploy/AGENTS.md`](deploy/AGENTS.md).

### Measuring performance (Part 2.5)

Metrics are collected with `deploy/measure.sh` (run on the VM) around a load window; load comes from
`src/load_test.py` or the real sender. `measure.sh` snapshots the receiver's CPU time and cgroup
memory (`systemctl`) and the `eth0` byte counters before/after and prints the deltas; `load_test.py`
posts frames and reports round-trip and the server's `processing_ms`. We take a baseline (idle), a
burst of frames, and an egress window (clients polling the page), and report medians rather than a
single number.

**Detection efficiency** is measured as **throughput / latency** (fps and ms per frame), not as an
accuracy score: the test clip has **no ground-truth labels**, so precision/recall cannot be measured
and the local-YOLO count comparison is a **sanity proxy only** — the same definition used in Part 3
([`docs/performance.md`](docs/performance.md)).

```sh
# on the VM
bash deploy/measure.sh baseline  --seconds 15               # idle
bash deploy/measure.sh inference --self-load --frames 12   # compute + latency over localhost
bash deploy/measure.sh egress    --seconds 20              # while clients poll the page
```

Measured on the `Standard_B2ats_v2` (2 vCPU, 887 MiB RAM, 2 GB swap):

| Scenario | CPU (process) | Memory (cgroup) | Network (eth0) | Latency |
| --- | --- | --- | --- | --- |
| Idle (15 s) | 0.00 s (0%) | 509 MB current / 527 MB peak; 128 MB swap | ≈ 0 | — |
| Inference, 12 frames | 4.82 s (20% of one core) | peak 527 MB; swap 128 → 324 MB | negligible | median **0.37 s**/frame (first 15.7 s, second 2.3 s) |
| Egress, 40 page polls (20 s) | ≈ 0 | peak 527 MB | **tx 26 MB (10.5 Mbps)** | — |

Findings:

- **Steady-state detection ≈ 0.37 s/frame** (~2.7 fps for one stream). Startup is the expensive part:
  ~11 s of model load plus a ~16 s first inference, so the model is warmed at startup and the client
  timeout must exceed it.
- **Memory, not CPU, is the binding constraint.** A burst uses only ~20% of one core, but the service
  holds ~0.5 GB and pushes 128 → 324 MB into swap on the 887 MiB VM. More RAM (or a smaller
  model/`imgsz`) would help more than more CPU.
- **Egress dwarfs ingress.** The frontend re-downloads the ~0.5 MB annotated frame every second, so a
  single open page costs ~43 GB/day (~1.3 TB/month) — versus ~7 GB/day of frames uploaded at
  1 frame/5 s (ingress is free on Azure). Levers: downscale the served image, lower the poll rate, or
  serve only the chart. Egress beyond the 100 GB/month free allowance is the main cost risk, far above
  the ~US$0.01/h `Standard_B2ats_v2` itself.

**Cost protocol.** Actual spend is read by hand from **Portal → Cost Management → Cost analysis**,
scoped to the resource group `<serverless-resource-group>`, with a **custom date range per measurement window**
and currency **EUR** (`az consumption` returns null costs on this student subscription). The same
protocol covers the Part 2.5, 3.6, 4.2, and 4.3 windows; because Cost Management is daily-granular, a
sub-minute window is reported as the resource group's spend over the covering day/window. See
[`docs/performance.md`](docs/performance.md).

## Serverless offload (Part 3)

Part 3 replaces the always-on VM with a triggered Azure Function. The sender uploads each frame to
the private `raw` container of the storage account `<storage-account>` every 0.5 s; an **Event Grid**
`BlobCreated` event invokes the Flex Consumption Function App `<function-app>`, which counts people with
**Azure AI Vision** (Image Analysis 4.0 `people`), draws the boxes, writes `processed_frame.jpg` and
appends `database.csv` into the public `$web` container, then deletes the raw blob. The same `web/`
frontend is served from `$web` and polls those two files — no API or database. Full design
(components, data flow, the no-recursion property): [`docs/architecture.md`](docs/architecture.md).

```sh
bash deploy/deploy_function.sh            # build the bundle + az zip-deploy (remote build)
bash deploy/deploy_web.sh                 # publish web/ (index.html, style.css, script.js, not_found.html) to $web
bash deploy/stream_serverless.sh          # upload one frame to raw every 0.5 s (Ctrl-C to stop)
bash deploy/provision_part3.sh audit      # read-only inventory of the Part 3 resources
# page: https://<static-site-host>/
```

`deploy/deploy_web.sh` (re)publishes the static site to `$web` without touching the pipeline's
runtime blobs; `deploy/provision_part3.sh` audits or recreates the Part 3 infrastructure (`audit` is
read-only, `create --yes` is the gated path) — see
[`docs/architecture.md`](docs/architecture.md#reproducing-the-infrastructure).

## Multi-camera (Part 4)

Part 4 scales the sender to several cameras at 1 frame / 5 s each and measures where each platform
gives out. `src/local_stream.py --cameras N` drives `N` pseudo-cameras from one local clip through
the `src/multicam.py` scheduler (a single decoder, `N` phase-offset workers), uploading to the VM
receiver (`--cloud-url`) or the `raw` container (`--blob-connection-string`); `N ≥ 2` switches the
CSV to `Timestamp,Camera,Person_Count` and writes one annotated frame per camera under
`frames/<camera>.jpg`. By default every camera shows the same newest frame; `--phase-offset S` makes
each successive camera sample the clip `S` seconds behind the previous (kept in a small, bounded
buffer), so the cameras show different points in time. The limits are found by sweeping `N` with
`deploy/sweep_vm.sh` (Part 4.2) and `deploy/sweep_serverless.sh` (Part 4.3):

Driving N pseudo-cameras from **one** clip is a deliberate **load model**: the single shared decoder
keeps the local sender cheap, so a sweep measures the **server under test**, not the sender (the
brief allows sending from "the same local device"). N distinct sources are a possible extension, but
N local decoders can make the sender the bottleneck.

- **VM** — ~10 cameras comfortably, 12–13 sitting at the throughput edge (non-deterministic), and
  ≥14 collapsing (a memory/swap spiral on the 887 MiB `Standard_B2ats_v2`).
- **Serverless** — ~128 cameras (~26 fps), roughly 10× the VM; the ceiling is **AI Vision
  throughput** and the failure mode is a 429 throttling/retry backlog, not memory.

Method, result tables, and the raw sweep captures: [`docs/performance.md`](docs/performance.md) and
[`docs/sweeps/`](docs/sweeps/).

## Getting started

**Requirements:** Python ≥ 3.10 and the dependencies from [`pyproject.toml`](pyproject.toml)
installed into a virtualenv (`pip install -e .`); lint/format with **ruff** (`line-length = 100`,
double quotes).

```sh
python3 -m venv venv
source venv/bin/activate
pip install -e .

python scripts/download_video.py "https://www.youtube.com/watch?v=3FXUw98rrUY"
python src/local_test_platform.py   # run from the repo root; YOLO weights download automatically
```

## Course info

Practical work = **70%** of the final grade; this assignment is **60%** of that. Deadlines:
Assignment 1 on **18 Oct**, Assignment 2 (Docker + Quantum) on **25 Oct**.
