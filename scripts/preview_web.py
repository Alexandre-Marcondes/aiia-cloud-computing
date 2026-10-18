"""Serve the web/ frontend locally with dummy data, for offline layout checks.

Builds a throwaway directory with ``web/index.html``, ``web/script.js``, a
generated ``database.csv`` (smooth random-ish counts), a ``processing.csv``
(per-frame telemetry, ``Timestamp,Camera,ProcessingMs,QueueMs,ServiceMs``), and
a frame image, then serves it over HTTP on localhost. The page *must* be served
over http:// (not ``file://``) because ``script.js`` fetches the CSVs.

Nothing is uploaded to Azure and nothing in ``web/`` is modified — the copy
lives in a temp dir. Use it to iterate on the layout without deploying::

    venv/bin/python scripts/preview_web.py --port 8137
    # then open http://127.0.0.1:8137/ and resize the window

Pass ``--cameras N`` (N > 1) to emit a multi-camera CSV
(``Timestamp,Camera,Person_Count``) plus ``frames/cam-<i>.jpg`` tiles instead of
the legacy single ``database.csv`` + ``processed_frame.jpg``. The processing
telemetry mirrors the camera mode (``cam`` for N=1, ``cam-1..N`` for multi):
service time stays flat (~350-450 ms) while the queue wait sits near zero. Pass
``--queue-ramp N`` to make the queue wait climb to ``N`` ms across the file, so
the "flat service / growing queue" clip is visible. Pass ``--no-telemetry`` to
omit ``processing.csv`` entirely, to check that the processing panel hides
itself while the counts chart keeps rendering.

A tiny debug script is injected into the temp copy that writes the measured
panel/canvas widths into the page title, so headless Chrome can report them
without a browser GUI.
"""

import argparse
import math
import shutil
import tempfile
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB = REPO_ROOT / "web"

DEBUG_SNIPPET = """
<script>
function dbgWidths() {
  function w(sel) { var el = document.querySelector(sel);
    return el ? (Math.round(el.clientWidth) + 'x' + Math.round(el.clientHeight)) : '-1'; }
  var layout = document.querySelector('.dashboard') || document.querySelector('.layout');
  var proc = document.getElementById('processingPanel');
  var procState = (!proc || proc.hidden) ? 'off'
      : ('on/' + ((typeof processingChart !== 'undefined' && processingChart)
                  ? processingChart.data.datasets.length : -1));
  var txt = 'cols=' + (layout ? getComputedStyle(layout).gridTemplateColumns : '-') +
            ' chart=' + w('.chart-panel') + ' canvas=' + w('#personCountChart') +
            ' pcanvas=' + w('#processingChart') +
            ' image=' + w('.image-panel') + ' img=' + w('#reloadImage') +
            ' views=' + w('.views') + ' framesbox=' + w('#frames') +
            ' frames=' + document.querySelectorAll('#frames img').length +
            ' series=' + ((typeof chart !== 'undefined' && chart)
                          ? chart.data.datasets.length : -1) +
            ' processing=' + procState +
            ' histogram=' + ((typeof histogramChart !== 'undefined' && histogramChart)
                             ? histogramChart.data.datasets.length : -1) +
            ' hbars=' + ((typeof histogramChart !== 'undefined' && histogramChart)
                         ? histogramChart.data.datasets.reduce(function (sum, ds) {
                             return sum + ds.data.reduce(function (a, b) { return a + b; }, 0);
                           }, 0) : -1) +
            ' dpr=' + devicePixelRatio + ' innerW=' + innerWidth;
  document.title = 'MEASURE ' + txt;
  var el = document.getElementById('dbg');
  if (!el) {
    el = document.createElement('pre');
    el.id = 'dbg';
    el.style.cssText = 'background:#ffff66;padding:6px;margin:8px 0 0;white-space:pre-wrap';
    document.body.appendChild(el);
  }
  el.textContent = txt;
}
setTimeout(dbgWidths, 1200);
setInterval(dbgWidths, 1000);
</script>
"""

# Injects a runtime container resize (shrinks .layout width) and reports the
# canvas width before/after, to test whether the chart re-fits on resize.
RESIZE_TEST_SNIPPET = """
<script>
function W(sel) { var el = document.querySelector(sel); return el ? el.clientWidth : -1; }
var before = 'pending';
setTimeout(function () {
  before = 'chart=' + W('.chart-panel') + ' canvas=' + W('#personCountChart');
}, 1400);
setTimeout(function () { document.querySelector('.dashboard').style.width = '40%'; }, 1800);
setTimeout(function () {
  document.title = 'MEASURE before[' + before + '] after[chart=' + W('.chart-panel') +
                   ' canvas=' + W('#personCountChart') + ']';
}, 3400);
</script>
"""

# Dispatches real PointerEvents on the splitter (drag it right) and reports the
# charts/video widths before and after, to test the draggable divider.
SPLIT_TEST_SNIPPET = """
<script>
function _pt(type, x) {
  var el = document.getElementById('splitter');
  el.dispatchEvent(new PointerEvent(type, {clientX: x, clientY: 200, bubbles: true, pointerId: 1}));
}
function _w(sel) { var el = document.querySelector(sel); return el ? el.clientWidth : -1; }
var _before = 'pending';
setTimeout(function () { _before = 'charts=' + _w('.charts') + ' views=' + _w('.views'); }, 1400);
setTimeout(function () {
  var r = document.querySelector('.dashboard').getBoundingClientRect();
  _pt('pointerdown', r.left + r.width * 0.30);
  _pt('pointermove', r.left + r.width * 0.55);
  _pt('pointerup', r.left + r.width * 0.55);
}, 1800);
setTimeout(function () {
  document.title = 'MEASURE before[' + _before + '] after[charts=' + _w('.charts') +
                   ' views=' + _w('.views') + ']';
}, 3600);
</script>
"""


def service_value(index):
    """Plausible per-frame service time (ms): ~350-450, flat-ish noise."""
    return 400 + 40 * math.sin(index / 7.0) + 10 * math.sin(index / 2.3)


def queue_value(index, total, ramp):
    """Queue wait (ms): near-zero jitter by default; when ``ramp`` > 0 it grows
    linearly to ``ramp`` across the series (to demo the flat-service/growing-queue
    clip)."""
    jitter = 10 * (1 + math.sin(index / 5.0))
    if ramp > 0:
        jitter += ramp * (index / max(1, total - 1))
    return max(0.0, jitter)


def build_csv(directory, samples, interval, telemetry=True, queue_ramp=0):
    now = datetime.now()
    lines = ["Timestamp,Person_Count"]
    processing = ["Timestamp,Camera,ProcessingMs,QueueMs,ServiceMs"]
    for i in range(samples):
        when = now - timedelta(seconds=(samples - i) * interval)
        stamp = when.strftime("%Y-%m-%d %H:%M:%S")
        count = int(12 + 12 * math.sin(i / 40.0) + 4 * math.sin(i / 3.0))
        lines.append(f"{stamp},{max(0, count)}")
        service = service_value(i)
        queue = queue_value(i, samples, queue_ramp)
        processing.append(f"{stamp},cam,{int(queue + service)},{int(queue)},{int(service)}")
    (directory / "database.csv").write_text("\n".join(lines) + "\n")
    if telemetry:
        (directory / "processing.csv").write_text("\n".join(processing) + "\n")


def build_csv_v2(directory, samples, interval, cameras, telemetry=True, queue_ramp=0):
    """Write the multi-camera CSV (``Timestamp,Camera,Person_Count``).

    Each of the ``samples`` rounds emits one row per camera, phase-staggered
    within the round just like the sender, so the file is interleaved. The
    processing telemetry emits one row per counts row.
    """
    now = datetime.now()
    step = interval / cameras
    lines = ["Timestamp,Camera,Person_Count"]
    processing = ["Timestamp,Camera,ProcessingMs,QueueMs,ServiceMs"]
    total = samples * cameras
    for i in range(samples):
        round_seconds = (samples - i) * interval
        for cam in range(1, cameras + 1):
            when = now - timedelta(seconds=round_seconds) + timedelta(seconds=(cam - 1) * step)
            stamp = when.strftime("%Y-%m-%d %H:%M:%S")
            count = int(12 + 12 * math.sin((i + cam) / 40.0) + 4 * math.sin(i / 3.0 + cam))
            lines.append(f"{stamp},cam-{cam},{max(0, count)}")
            frame = i * cameras + (cam - 1)
            service = service_value(frame)
            queue = queue_value(frame, total, queue_ramp)
            processing.append(
                f"{stamp},cam-{cam},{int(queue + service)},{int(queue)},{int(service)}"
            )
    (directory / "database.csv").write_text("\n".join(lines) + "\n")
    if telemetry:
        (directory / "processing.csv").write_text("\n".join(processing) + "\n")


def build_frames(directory, cameras, image):
    """Write ``frames/cam-<i>.jpg`` tiles (copy the sample image, or empty)."""
    frames = directory / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    for cam in range(1, cameras + 1):
        target = frames / f"cam-{cam}.jpg"
        if image.exists():
            shutil.copy(image, target)
        else:
            target.write_bytes(b"")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8137)
    parser.add_argument("--samples", type=int, default=600)
    parser.add_argument(
        "--cameras",
        type=int,
        default=1,
        help="emit a multi-camera CSV + frames/cam-<i>.jpg tiles (default: 1, legacy)",
    )
    parser.add_argument(
        "--no-telemetry",
        action="store_true",
        help="omit processing.csv, to check the processing panel hides itself",
    )
    parser.add_argument(
        "--queue-ramp",
        type=int,
        default=0,
        metavar="N",
        help="ramp the queue wait up to N ms across the file (0 = flat near-zero)",
    )
    parser.add_argument("--image", default=str(REPO_ROOT / "data" / "processed_frame.jpg"))
    parser.add_argument(
        "--debug",
        action="store_true",
        help="inject a yellow readout of panel/canvas/image widths at the page foot",
    )
    parser.add_argument(
        "--resize-test",
        action="store_true",
        help="inject a runtime container resize (for headless verification)",
    )
    parser.add_argument(
        "--split-test",
        action="store_true",
        help="inject a splitter drag (for headless verification)",
    )
    args = parser.parse_args()

    if args.cameras < 1:
        parser.error("--cameras must be >= 1")
    if args.queue_ramp < 0:
        parser.error("--queue-ramp must be >= 0")

    if args.resize_test:
        snippet = RESIZE_TEST_SNIPPET
    elif args.split_test:
        snippet = SPLIT_TEST_SNIPPET
    elif args.debug:
        snippet = DEBUG_SNIPPET
    else:
        snippet = ""

    tmp = Path(tempfile.mkdtemp(prefix="sls-web-preview-"))
    html = (WEB / "index.html").read_text()
    if snippet:
        html = html.replace("</body>", snippet + "</body>")
    (tmp / "index.html").write_text(html)
    shutil.copy(WEB / "script.js", tmp / "script.js")
    shutil.copy(WEB / "style.css", tmp / "style.css")

    image = Path(args.image)
    telemetry = not args.no_telemetry
    if args.cameras > 1:
        build_csv_v2(
            tmp, args.samples, 0.5, args.cameras, telemetry=telemetry, queue_ramp=args.queue_ramp
        )
        build_frames(tmp, args.cameras, image)
    else:
        build_csv(tmp, args.samples, 0.5, telemetry=telemetry, queue_ramp=args.queue_ramp)
        if image.exists():
            shutil.copy(image, tmp / "processed_frame.jpg")
        else:
            (tmp / "processed_frame.jpg").write_bytes(b"")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kwargs):
            super().__init__(*a, directory=str(tmp), **kwargs)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    print(f"serving {tmp}\n  -> http://127.0.0.1:{args.port}/   (Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
