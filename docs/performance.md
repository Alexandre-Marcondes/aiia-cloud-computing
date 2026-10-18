# Performance measurement (Part 3)

Task 3.6 asks for three things: **detection efficiency**, **monetary cost**, and **response
time**. This page records what we measure for each, where every number comes from, and how to
collect it — it is the working reference for the report's Part 3 section. It describes the
*measurement*, not the architecture (see [`architecture.md`](architecture.md)).

All instruments here are **read-only** (`show`/`list`/`query`); none changes the deployment.

## Instruments

| Instrument | Measures | Kind |
| --- | --- | --- |
| [`src/measure_serverless.py`](../src/measure_serverless.py) | upload→visible latency (client-observed, end-to-end) | client probe |
| [`deploy/measure_part3.sh`](../deploy/measure_part3.sh) | server-side response time, compute, AI, storage, event delivery | `az` queries |
| Portal → **Cost Management → Cost analysis** | actual spend (EUR) | manual, scoped to RG |
| Portal → Function App → **Log stream** / App Insights → **Live Metrics** | live view during a run | manual |

## Response time

Two complementary numbers:

- **Server-side** — Application Insights `AppRequests` has one row per invocation
  (`Name=process_frame`) with `DurationMs`; `AppDependencies` adds per-blob-stage timings. This is
  the function's own time and **excludes** Event Grid delivery and the client's poll.
- **End-to-end (upload→visible)** — `src/measure_serverless.py` uploads a frame and waits for
  `$web/database.csv`'s ETag to change, then reports min/mean/median/p95/max. Because the pipeline
  is asynchronous (the function writes to a different container, so nothing comes back), frames are
  sent one at a time so each update is attributed to its own upload. It also reports the raw-blob
  deletion latency and the number of CSV rows added (a duplicate/loss check).

> **Gap to be aware of:** the Vision call uses `requests.post`, not an Azure SDK, so it is *not*
> auto-instrumented — it does not appear in `AppDependencies`. Its latency is visible only
> coarsely via the Cognitive Services `Latency` metric. Per-call Vision timing is **not required**
> by the brief, so we do not add SDK instrumentation.

## Detection efficiency

**Definition.** For this practice, detection efficiency is **throughput / latency**: frames per
second (fps) and milliseconds per frame — the receiver's per-frame `ProcessingMs = QueueMs +
ServiceMs` under load (Parts 2.5, 4.2, 4.3), and, on the serverless path, the AI-Vision **call
success rate** (`SuccessfulCalls` / `TotalCalls`). It is *not* an accuracy score: the test clip has
**no ground-truth labels**, so precision/recall cannot be measured. Comparing the counts with a local
YOLO run over the same clip is a **sanity proxy only**, never a reported metric.

Instruments behind the number:

- **Processing cost per frame** — Functions Flex metrics `OnDemandFunctionExecutionCount` and
  `OnDemandFunctionExecutionUnits` (units are MB·ms, the billable compute unit; note Flex uses the
  `OnDemand*` names, the generic `FunctionExecutionCount` does not exist here).
- **Throughput / latency** — the per-frame `ProcessingMs` in `processing.csv` and the server-side
  invocation duration from Application Insights (see **Response time**).
- **Serverless success rate** — AI Vision `TotalCalls` / `SuccessfulCalls` / `Latency`; a falling
  success rate is the efficiency loss that marks the 4.3 ceiling.

## Monetary cost

Two read-only ways to read actual spend, both in `EUR`:

- **`deploy/cost.sh`** (reproducible) — queries the Cost Management REST API
  (`Microsoft.CostManagement/query`, `ActualCost`) directly, because `az consumption usage list`
  returns **null** costs on this student subscription; prints per-day totals + a per-service breakdown.
- **Portal → Cost Management → Cost analysis** — the same numbers by hand.

⚠️ The resource groups **differ by part**: the VM lives in `<vm-resource-group>`, the serverless stack in
`<serverless-resource-group>`.

| Component | Cost driver |
| --- | --- |
| AI Vision (ComputerVision S1) | one call per uploaded frame — **the dominant cost** |
| Functions (Flex Consumption) | executions + execution units (MB·ms) — bills ≈€0 here |
| Storage | transactions + capacity (tiny; raw is deleted) + **egress** |
| Event Grid | free tier at these volumes (€0.05 / month) |
| VM compute (`Standard_B2ats_v2`) | hourly — **bills €0 on this student subscription** |

**Measured (2026-10-17)** — `bash deploy/cost.sh --from 2026-10-17 --to 2026-10-18`:

| Scope | Oct 17 | Month (Oct 1–17) | Drivers |
| --- | --- | --- | --- |
| RG `<vm-resource-group>` (Parts 2.5, 4.2) | **€0.031** | **€1.51** | operating-system disk only; Virtual Machines €0.00 |
| RG `<serverless-resource-group>` (Parts 3.6, 4.3) | **€0.007** (Storage only) | **€30.26** | Foundry Tools (AI Vision) €29.01, Storage €1.20, Event Grid €0.05 |

- **AI Vision dominates**: ≈€29 of the €30.26 serverless month. It all posted on **Oct 11** (the N=256
  sweep day), and the meter **lags several days** — the Oct 17 Vision line was still pending when these
  figures were read, so the Oct 17 serverless figure is a **lower bound** (re-run `cost.sh` later to
  pick it up).
- **The VM compute bills €0.00** for the whole month on this student subscription; the VM RG's only
  cost is the ≈€1.51 OS disk (≈€0.03/day).
- **Egress** is the recurring lever on the served page: the frontend re-downloads the annotated frame
  (≈0.53 MB) each poll — the same finding as Part 2 (T1b).

### Cost protocol

`bash deploy/cost.sh [--from YYYY-MM-DD --to YYYY-MM-DD] [--rg NAME]` (read-only; default window the
current month through tomorrow). Cost Management is **daily-granular**, so a 60 s window is reported as
the covering day, not an isolated figure — record the day. The portal path (**Cost Management → Cost
analysis**, scope the RG, `EUR`) returns the same numbers.

## Measurement protocol (one session)

1. **Baseline** — delete `$web/database.csv` and any `raw/*` so the window is unambiguous.
2. **Load** — run the pipeline at the spec cadence (local sender at 0.5 s) or the probe.
3. **Collect** —
   - `venv/bin/python src/measure_serverless.py --frames 10 --interval 0.5` (e2e),
   - `bash deploy/measure_part3.sh --minutes 15` (server-side),
   - screenshot Cost Management for the window.
4. **Record** the numbers below.

## Results

One healthy run of a few minutes at the spec rate (one frame every 0.5 s, ≈2 fps):

| Metric | Source | Value |
| --- | --- | --- |
| invocations | App Insights | 503 requests, 0 failed, 0 exceptions |
| invocation duration (mean / p95 / max) | App Insights | 0.65 s / 0.77 s / 19.6 s (cold start) |
| executions / execution units | Functions metrics | ≈300 / 400.2 M MB·ms (≈391 GB·s) |
| Vision calls / latency | Cognitive Services metrics | 371 calls, ≈0.43 s each |
| event delivery (matched / delivered / failed) | Event Grid (system topic) | 371 / 371 / 0 |
| storage ingress / egress | Storage metrics (10 min) | 252.6 MB / 175.8 MB |
| upload→visible (mean / p95) | `measure_serverless.py` | *not run* (optional instrument, ready) |
| cost for window | Cost Management | under €0.01 for the whole resource group |

(Counts differ across sources — see the caveat below; Event Grid matched = Vision calls is the
reliable frames-processed figure.)

## Caveats

- **Counter divergence.** The invocation counts from different systems do **not** agree for the
  same window — e.g. one 10-minute run gave `AppRequests` (App Insights) = 503,
  `OnDemandFunctionExecutionCount` (ARM metrics) = 296, and Event Grid `MatchedEventCount` / AI
  Vision `TotalCalls` = 371. They come from independent telemetry pipelines with their own
  aggregation windows, sampling, and ingestion lag; the ARM metrics in particular under-report at
  short windows. The **Event Grid matched count (= Vision calls)** is the reliable "frames
  processed" figure. Always record the source of each number and don't expect them to reconcile
  exactly.
- CSV timestamps are second-resolution and stamped at *processing* time, so per-frame wall-clock
  ordering comes from the probe's ETag timing, not from the CSV.
- Flex metrics use the `OnDemand*` names; Event Grid metrics live on the **system topic**
  (`<storage>-raw`), not the subscription.
- A lone `ConnectionAbortedException` ("request stream aborted") can appear in `AppExceptions`; it
  is a benign aborted HTTP request, unrelated to frame processing.

## Part 4 — multi-camera processing limit

Tasks 4.2 and 4.3 ask how many cameras each serving platform can keep up with at the spec cadence
of **1 frame / 5 s per camera**. We drive N pseudo-cameras from one local clip
(`src/local_stream.py --cameras N`) and let the *server* do the detection, so the measured limit is
the platform's, not the sender's — the local machine decodes a single clip and only uploads frames.

- **4.2 (Part 2 VM, IaaS)** — `deploy/measure.sh` (on the VM) samples the receiver's CPU time,
  cgroup memory, and NIC counters around the streaming window; the knee is found by sweeping N.
- **4.3 (Part 3 serverless)** — `deploy/measure_part3.sh` collects the server-side telemetry for
  the window (response time from Log Analytics; executions / Vision calls / storage / event delivery
  from Azure Monitor); cost is read from Portal Cost Management.

> **Response-time metric (4.x).** The 4.x sweep's response time is the **receiver-side per-frame
> service + queue wait** — `ProcessingMs = QueueMs + ServiceMs` in the served `processing.csv` —
> measured under the **real N-camera load**. The Part 2.5 client round-trip
> ([`src/load_test.py`](../src/load_test.py)) is a separate **synthetic** probe (one client posting
> frames over localhost) and is **not** part of the 4.x sweep.

### Instruments

| Instrument | Measures | Kind |
| --- | --- | --- |
| [`deploy/sweep_vm.sh`](../deploy/sweep_vm.sh) | per-N: sender run + receiver CPU/mem/network via `measure.sh` over SSH | sweep driver (4.2) |
| [`deploy/sweep_serverless.sh`](../deploy/sweep_serverless.sh) | per-N: sender run to `raw`, then the `measure_part3.sh` report | sweep driver (4.3) |
| Portal → **Cost Management → Cost analysis** | actual spend (EUR) per sweep | manual, scoped to RG |

### Per-N protocol

1. Before each N, `deploy/sweep_vm.sh` resets the receiver's document root (`database.csv`,
   `processing.csv`, `frames/`) so the window is unambiguous.
2. Stream for a **60 s window** per N (`--seconds 60`); `--cooldown` drains swap between runs, or
   `--restart` restarts the receiver for a clean state (the VM does not self-recover from swap
   pressure — a restart clears the backlog but not swap).
3. Capture the `measure.sh` report, the fleet log, and the per-N telemetry (`processing.csv`).

Committed raw captures (verbatim tool output):

- [`sweeps/vm-4.2-raw.txt`](sweeps/vm-4.2-raw.txt) — exploratory N = 1–10.
- [`sweeps/vm-4.2-cooldown-sweep.txt`](sweeps/vm-4.2-cooldown-sweep.txt) — N = 4,6,8,10,12,13,14,16, cooldown between N.
- [`sweeps/vm-4.2-fragility.txt`](sweeps/vm-4.2-fragility.txt) — the same points re-run on a degraded VM.

Committed per-N `processing.csv` slices (header + a few rows, produced with
[`scripts/slice_csv.py`](../scripts/slice_csv.py); the full CSVs stay in `data/sweeps/`):

- VM, healthy N=10 — [`sweeps/vm-4.2-processing-N10.txt`](sweeps/vm-4.2-processing-N10.txt).
- VM, collapsing N=14 — [`sweeps/vm-4.2-processing-N14.txt`](sweeps/vm-4.2-processing-N14.txt).

> **Pending.** The serverless per-frame slices (N=128 healthy, N=144 overflow) are **not captured
> yet**: they need a live `deploy/sweep_serverless.sh` run, which downloads `$web/processing.csv` per N
> (the tooling is in place). Tracked as a follow-up measurement task (§6 H3 of the plan); until then
> the serverless table above rests on the `raw`-backlog capture.

### VM (4.2) findings

Sweep at the spec cadence (**1 frame / 5 s per camera**), 60 s window per N, with a cooldown so swap
drains between runs. `QueueMs` = wait for the processing lock; `ServiceMs` = detect + write. The
receiver runs on the live **`Standard_B2ats_v2`** VM (2 vCPU / 1 GiB; the OS reports ~887 MB usable,
the figure the analysis below uses).

| N | CPU (% of one core) | frames | QueueMs mean (max) | ServiceMs mean | outcome |
| --- | --- | --- | --- | --- | --- |
| 4 | 32% | 48 | ~600 (3942)\* | 725\* | healthy |
| 6 | 46% | 73 | 0 (0) | 381 | healthy |
| 8 | 62% | 97 | 0 (0) | 381 | healthy |
| 10 | 78% | 121 | ~0 (26) | 381 | healthy |
| 12 | 94% | 145 | 7 (170) | 384 | healthy |
| 13 | **102%** | 157 | 165 (518) | 387 | saturated — the limit |
| 14 | 22% | 41 | 16 191 (50 040) | 2116 | **collapse** |
| 16 | 14% | 27 | 34 424 (75 441) | 3888 | **collapse** |

\* N=4 had a single cold-start spike (~5 s) that skews its mean; ignore it.

Per-frame `processing.csv` evidence for the two regimes:
[`sweeps/vm-4.2-processing-N10.txt`](sweeps/vm-4.2-processing-N10.txt) (healthy — flat `QueueMs`)
and [`sweeps/vm-4.2-processing-N14.txt`](sweeps/vm-4.2-processing-N14.txt) (collapsing — the
queue ramp).

- **Throughput knee at N = 13.** CPU rises roughly linearly (≈ +7.7% of one core per camera) to
  **102% at N=13**, while `QueueMs` stays ≈0 and `ServiceMs` a steady ~385 ms up to N=13. At N=14 the
  CPU *falls* to 22% — the box is thrashing, not computing — and `QueueMs` explodes to **50 s**
  (mean 16 s), `ServiceMs` degrades to seconds, and the client times out.
- **The limit is memory-bound and unstable, not CPU-bound.** The receiver process is ~512 MB RSS on
  an 887 MB VM, leaving ~180 MB headroom; the box runs on swap even at rest. N=13 fully saturates the
  single processing core, so one camera past it backs the queue up, memory pressure → swap thrash →
  the *service* time itself collapses (0.35 s → 2–21 s): a death spiral.
- **It degrades cumulatively and does not self-recover.** Re-running N=13, or 12/13/14, after heavy
  runs (swap already ~1 GB) collapses *every* point, even with a per-N service restart. See
  [`sweeps/vm-4.2-fragility.txt`](sweeps/vm-4.2-fragility.txt).
- **A full reboot restores the baseline, not the edge.** After `az vm restart` (clears swap + page
  cache), N=4 was healthy again (31% CPU, no timeouts) — so the VM is not damaged — but N=13 *still*
  collapsed (`QueueMs` 30 s, `ServiceMs` 4 s). The high-N failure is the **throughput edge**
  (`N/5 ≈ 1/service`), which no restart can fix — you cannot restart your way to more CPU. See
  [`sweeps/vm-4.2-reboot.txt`](sweeps/vm-4.2-reboot.txt).

**4.2 result: at 1 frame / 5 s the VM serves ~10 cameras comfortably; 12–13 sit right at the
throughput edge (`N/5 ≈ 1/service ≈ 2.6 fps`) and are non-deterministic (13 came out healthy once and
collapsed twice); 14 or more always collapses. Memory is what makes the failure mode so severe — the
1 GiB VM thrashes and does not self-recover — but the steady-state ceiling itself is set by the single
processing core, not by memory.**

> **Telemetry.** Response time is now captured per frame as `ProcessingMs = QueueMs + ServiceMs` in
> the served `processing.csv`; the page's second chart plots service vs queue wait, so the clip reads
> as a sustained **queue-wait ramp**. Cost is the `Standard_B2ats_v2` hourly rate pro-rated over the window
> (≈ €0.0003 for 60 s).

### Serverless (4.3) findings

Method: the same fleet, but uploading to the `raw` container (fire-and-forget, so the
server cannot backpressure the sender). The direct signal is the **`raw` backlog** — the
function deletes each blob after processing, so the count is the unprocessed work —
sampled every 10 s; `deploy/measure_part3.sh` adds the server-side telemetry. The sender
is not the limit: N=256 uploaded 3073/3072 frames (51 fps).

Sweep at the spec cadence (1 frame / 5 s per camera), 60 s per N. Raw capture:
[`sweeps/serverless-4.3-raw.txt`](sweeps/serverless-4.3-raw.txt).

| N | offered (fps) | `raw` backlog during run | after run | verdict |
| --- | --- | --- | --- | --- |
| 8 / 16 | 1.6 / 3.2 | ~0 | 0 | keeps up |
| 48 | 9.6 | ~10 | 0 | keeps up |
| 64 | 12.8 | ~13 | 0 | keeps up |
| **128** | **25.6** | peak ~53 | **drains to 0** | **keeps up** |
| 144 | 28.8 | grows to 243 | stalls at 87 | overflow |
| 160 | 32.0 | grows to 352 | stalls at 163 | overflow |
| 192 | 38.4 | grows to 472 | stalls at 252 | overflow |
| 256 | 51.2 | grows to ~800 | stalls at 625 | overflow |

Per-frame `processing.csv` evidence for the two serverless regimes (N=128 healthy, N=144 overflow) is
**pending** a live capture run — `deploy/sweep_serverless.sh` downloads `$web/processing.csv` per N
(tooling ready; see the follow-up measurement task). The VM regimes above are committed.

- **The serverless path serves up to ~128 cameras** (≈26 fps) at the spec cadence,
  overflowing beyond ~144. The ceiling (~26–29 fps) is the **AI Vision throughput**.
- **The failure mode is throttling, not memory.** At N=256 the metrics show 10 533
  invocations (6 548 failed, 9 765 exceptions) and AI Vision 24 950 calls with only
  **5 579 successful (22%)**: Vision returns 429 → our bounded retry + Event Grid
  redelivery → *more* Vision calls → more throttling — a **retry storm**, so the backlog
  freezes (stuck in Event Grid's backoff) instead of draining.

**4.3 result: ~128 cameras at 1 frame / 5 s (≈26 fps) — roughly 10× the VM's ~2.6 fps — and
a different failure mechanism (Vision-throttling backlog, not a memory death-spiral). Below
the ceiling the serverless path absorbs overload gracefully (it backlogs, then drains); past
it, the 429 retry storm is self-reinforcing.**

> **Caveats.** Azure Monitor windows lag (~1–5 min) and overlap between runs, so per-N
> metric counts are approximate — the `raw` backlog is the reliable signal. The retry storm
> is partly self-inflicted (our bounded 429-retry plus Event Grid redelivery); production
> would dead-letter poison events. Cost: Portal Cost Management (the student subscription
> reports none via `az`).
