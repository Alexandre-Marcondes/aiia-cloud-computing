# web/

Static frontend for the person-count data; part of the Teaching Team's provided sample process (see
`docs/AGENTS.md`). Served over HTTP (local, VM, or an Azure `$web` container); `file://` will not
work because `script.js` fetches `database.csv`.

- `index.html` — the dashboard markup (all styling lives in `style.css`): a `.page` wrapper with the
  `h1`, the `#lastUpdate` status line, and a two-column `.dashboard`. Left `.charts` stacks three
  `.panel`s, each an `h2.chart-title` above a `.chart-panel` canvas: the **person count over time**
  chart (`#personCountChart`), the per-frame **processing-time** chart (`#processingChart`, wrapped in
  `#processingPanel`, hidden until telemetry loads) and the always-visible **person-count histogram**
  (`#histogramChart`). Right `.views` holds the auto-reloading **latest annotated frame**
  (`<img src="processed_frame.jpg">`, single camera) or, in multi-camera mode, the
  `#frames.frames-grid` of `frames/<cam>.jpg` tiles. An empty `#splitter` sits between the two columns
  (the drag handle resized by `script.js`).
- `style.css` — the layout. The `.dashboard` is a **flex row** that fills the viewport height below
  the heading (`height: calc(100vh - 120px)`), with a draggable `.splitter` between the charts and the
  video; the charts' width is the `--chart-w` CSS variable (default 30%, page capped at
  `max-width: 1400px`). Both columns **stretch to the full height** — the charts' three rows divide it
  (so the charts are never capped by the video's height), and the video column keeps its height too.
  `.views` is a `position: relative` column whose `.image-panel` is `position: absolute; inset: 0`; the
  single video keeps its 16:9 shape (`width: 100%; aspect-ratio: 16/9`) and is **centred vertically**
  (`margin: auto 0`), so a tall column just adds even space above and below it. The chart canvases are
  `position: absolute` inside a `position: relative` `.chart-panel`, so they can't drive the row
  height. The `#frames` grid stacks 2-3 tiles in one column, sized to the full column height (a
  vertical strip of centred 16:9 thumbnails); 4+ add a `cols-2` class (`script.js`) that tiles them
  two-up and sizes them by width, so a 2x2 block stays 16:9 and is centred vertically. Portrait/narrow
  viewports stack to one column (auto height) with the video on top and hide the divider.
- `script.js` — parses the CSVs, builds the charts, and polls the CSV + image every second. The
  parser is **header-driven**: a `Camera` column yields multi-camera rows (`{timestamp, camera, personCount}`),
  otherwise the legacy `{timestamp, personCount}` path is used unchanged. The chart (Chart.js 2.9.4,
  v2 config) plots only real samples — no gap-filling — over a rolling window of the last
  `WINDOW_SAMPLES` with a `maxTicksLimit`ed 24-hour time axis, and a single reused `Chart` instance.
  In single mode it adds the `SMOOTHING`-wide rolling-average line; in multi mode it shows one raw
  series per camera (coloured from a fixed palette by camera order), **reconciled in place** each
  fetch — cameras added/dropped without ever recreating the `Chart` — and refreshes a
  `frames/<cam>.jpg` tile per camera. A `ResizeObserver` (plus a window-resize listener and a
  post-first-paint `resize()`) keeps the canvas fitted to its panel, since Chart.js 2 only re-fits on
  *window* resize. Timestamps are parsed as UTC (`Date.UTC`) so the browser shows local time, without
  the old `+4h` hack. It also shows the newest sample's timestamp (newest row overall in multi mode)
  and, from the HTTP `Date`/`Last-Modified` headers (both server clock, so no viewer-timezone issues),
  how many seconds ago the CSV last changed — a stalled streamer turns the line red. A **second,
  independent `Chart`** (`#processingChart`, its own `ResizeObserver`) plots the **`processing.csv`
  telemetry** — pinned schema `Timestamp,Camera,ProcessingMs,QueueMs,ServiceMs`, one row per
  processed frame, `Camera` being a camera id (`cam` in the legacy single-camera case, `cam-1..N` in
  multi). It is fetched each tick (`cache: 'no-store'`) and rendered over the same rolling window:
  one point per row (no per-camera grouping) with **two fixed series — service (ms, blue) and queue
  wait (ms, red/orange)** — so a queue build-up shows as a ramp while service time stays flat.
  Timestamps use the same UTC parsing, y-axis "time (ms)". Older three-column telemetry (no
  `QueueMs`/`ServiceMs`) falls back to a single `processing (ms)` series; `#processingPanel` is
  **hidden whenever `processing.csv` is missing/empty/unparseable**, so the counts view keeps working
  unchanged. The serverless `$web` site also serves `processing.csv` (the function writes it), so the
  panel is populated there too. A **third, independent `Chart`**
  (`#histogramChart`, a `bar` chart with its own `ResizeObserver`) renders the **person-count
  distribution**: the most recent `WINDOW_SAMPLES` rows are binned by integer count over the
  **observed range** (the window's min..max, not always from `0`), so a high-count scene is not
  stretched across an empty axis; x-axis "Person count", y-axis "Frames", `beginAtZero`. Both row
  shapes aggregate
  into one distribution, so it renders identically in single- and multi-camera modes; empty input
  yields an empty histogram without errors. It is always visible (never hidden). `setupSplitter()`
  wires the `.splitter` drag: pointer events (mouse/touch) set the `--chart-w` CSS variable (clamped
  15-60%), remembered in `localStorage` and adjustable with the left/right arrow keys; the charts'
  `ResizeObserver` re-fits the canvases on the resulting width change.
- `not_found.html` — 404 page.
