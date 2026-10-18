// Function to read and parse the CSV data. The schema is header-driven: a
// "Camera" column selects the multi-camera layout, otherwise the file is the
// legacy single-camera layout parsed exactly as before.
function parseCSV(csv) {
    const lines = csv.split("\n");
    const header = (lines[0] || "").split(",").map(field => field.trim());
    const cameraIndex = header.indexOf("Camera");
    const hasCamera = cameraIndex !== -1;
    const countIndex = hasCamera ? header.indexOf("Person_Count") : 1;
    const rows = [];

    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line === "") {
            continue; // skip blank/trailing lines
        }
        const parts = line.split(",");
        const timestamp = parts[0];
        const personCount = parseInt(parts[countIndex], 10);

        if (hasCamera) {
            const camera = parts[cameraIndex];
            if (
                timestamp === "" ||
                camera === undefined ||
                camera === "" ||
                Number.isNaN(personCount)
            ) {
                continue;
            }
            rows.push({ timestamp, camera, personCount });
            continue;
        }

        if (timestamp === "" || Number.isNaN(personCount)) {
            continue;
        }
        rows.push({ timestamp, personCount });
    }

    return { hasCamera, rows };
}

// Parse the per-frame telemetry CSV (pinned schema:
// Timestamp,Camera,ProcessingMs,QueueMs,ServiceMs), header-driven so column
// order does not matter. Returns null when the header is unparseable (missing
// required column), or a (possibly empty) array of rows. Older single-time
// telemetry (no QueueMs/ServiceMs) falls back to {timestamp, camera, processingMs}.
function parseProcessingCSV(csv) {
    const lines = csv.split("\n");
    const header = (lines[0] || "").split(",").map(field => field.trim());
    const timestampIndex = header.indexOf("Timestamp");
    const cameraIndex = header.indexOf("Camera");
    const processingIndex = header.indexOf("ProcessingMs");
    if (timestampIndex === -1 || cameraIndex === -1 || processingIndex === -1) {
        return null;
    }
    const queueIndex = header.indexOf("QueueMs");
    const serviceIndex = header.indexOf("ServiceMs");
    const hasSplit = queueIndex !== -1 && serviceIndex !== -1;

    const rows = [];
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line === "") {
            continue; // skip blank/trailing lines
        }
        const parts = line.split(",");
        const timestamp = parts[timestampIndex];
        const camera = parts[cameraIndex];
        const processingMs = parseFloat(parts[processingIndex]);
        if (
            timestamp === "" ||
            camera === undefined ||
            camera === "" ||
            Number.isNaN(processingMs)
        ) {
            continue;
        }
        if (hasSplit) {
            const queueMs = parseFloat(parts[queueIndex]);
            const serviceMs = parseFloat(parts[serviceIndex]);
            if (Number.isNaN(queueMs) || Number.isNaN(serviceMs)) {
                continue;
            }
            rows.push({ timestamp, camera, processingMs, queueMs, serviceMs });
            continue;
        }
        rows.push({ timestamp, camera, processingMs });
    }

    return rows;
}

// Rolling window (samples shown) and smoothing width for the average line.
const WINDOW_SAMPLES = 100;
const SMOOTHING = 5;
const Y_SUGGESTED_MAX = 40; // stable y-axis; avoids rescaling jitter each second

// Fixed palette for the per-camera series, assigned by camera position.
const CAMERA_COLORS = [
    'rgba(31, 119, 180, 1)',
    'rgba(255, 127, 14, 1)',
    'rgba(44, 160, 44, 1)',
    'rgba(214, 39, 40, 1)',
    'rgba(148, 103, 189, 1)',
    'rgba(140, 86, 75, 1)',
    'rgba(227, 119, 194, 1)',
    'rgba(188, 189, 34, 1)',
    'rgba(23, 190, 207, 1)',
    'rgba(127, 127, 127, 1)'
];

// Fixed colours for the telemetry chart: service time vs queue wait.
const SERVICE_COLOR = 'rgba(31, 119, 180, 1)'; // blue
const QUEUE_COLOR = 'rgba(214, 39, 40, 1)'; // red/orange

let chart = null; // the single live Chart instance, updated in place
let chartResizeObserver = null; // re-fits the canvas when its panel resizes
let chartMode = null; // 'single' | 'multi'; resets datasets when the schema flips
const cameraDatasets = {}; // multi mode: camera id -> reused dataset object

let processingChart = null; // second, independent Chart (per-frame telemetry)
let processingChartResizeObserver = null; // re-fits the processing canvas
let processingChartMode = null; // 'split' | 'single'; resets datasets on schema flip

let histogramChart = null; // third, independent Chart (person-count distribution)
let histogramChartResizeObserver = null; // re-fits the histogram canvas

// Re-fit the canvas to its panel (Chart.js reads the parent size on resize()).
function fitChart() {
    if (chart) {
        chart.resize();
    }
}

// Create the single Chart instance on first use. Kept separate from the render
// functions so both the single- and multi-camera views share one canvas and one
// ResizeObserver.
function ensureChart() {
    if (chart !== null) {
        return;
    }

    const ctx = document.getElementById('personCountChart').getContext('2d');
    chart = new Chart(ctx, {
        type: 'line',
        data: { labels: [], datasets: [] },
        options: {
            responsive: true,
            maintainAspectRatio: false, // fill the fixed-height .chart-panel
            animation: { duration: 0 },
            scales: {
                xAxes: [{
                    ticks: {
                        maxTicksLimit: 8,
                        autoSkip: true,
                        maxRotation: 0,
                        minRotation: 0
                    },
                    scaleLabel: { display: true, labelString: 'Time (local)' }
                }],
                yAxes: [{
                    ticks: { beginAtZero: true, suggestedMax: Y_SUGGESTED_MAX, precision: 0, maxTicksLimit: 5 },
                    scaleLabel: { display: true, labelString: 'Person count' }
                }]
            }
        }
    });

    // Chart.js 2 only re-fits on window resize; watch the container itself so
    // the canvas follows any layout change (grid/flex, panel resize). Also
    // re-fit once after first paint, since Chart.js can under-size the canvas
    // when it measures during initial layout.
    if (window.ResizeObserver) {
        chartResizeObserver = new ResizeObserver(fitChart);
        chartResizeObserver.observe(ctx.canvas.parentNode);
    }
    window.addEventListener('resize', fitChart);
    requestAnimationFrame(fitChart);
}

// Re-fit the processing canvas to its panel (its own ResizeObserver, since
// Chart.js 2 only re-fits on window resize).
function fitProcessingChart() {
    if (processingChart) {
        processingChart.resize();
    }
}

// Create the processing Chart instance on first use, mirroring ensureChart:
// one reused instance fitted by its own ResizeObserver.
function ensureProcessingChart() {
    if (processingChart !== null) {
        return;
    }

    const ctx = document.getElementById('processingChart').getContext('2d');
    processingChart = new Chart(ctx, {
        type: 'line',
        data: { labels: [], datasets: [] },
        options: {
            responsive: true,
            maintainAspectRatio: false, // fill the fixed-height .chart-panel
            animation: { duration: 0 },
            scales: {
                xAxes: [{
                    ticks: {
                        maxTicksLimit: 8,
                        autoSkip: true,
                        maxRotation: 0,
                        minRotation: 0
                    },
                    scaleLabel: { display: true, labelString: 'Time (local)' }
                }],
                yAxes: [{
                    ticks: { beginAtZero: true, precision: 0, maxTicksLimit: 5 },
                    scaleLabel: { display: true, labelString: 'time (ms)' }
                }]
            }
        }
    });

    if (window.ResizeObserver) {
        processingChartResizeObserver = new ResizeObserver(fitProcessingChart);
        processingChartResizeObserver.observe(ctx.canvas.parentNode);
    }
    window.addEventListener('resize', fitProcessingChart);
    requestAnimationFrame(fitProcessingChart);
}

// Re-fit the histogram canvas to its panel (its own ResizeObserver, since
// Chart.js 2 only re-fits on window resize).
function fitHistogramChart() {
    if (histogramChart) {
        histogramChart.resize();
    }
}

// Create the histogram Chart instance on first use, mirroring ensureProcessingChart:
// one reused bar Chart fitted by its own ResizeObserver.
function ensureHistogramChart() {
    if (histogramChart !== null) {
        return;
    }

    const ctx = document.getElementById('histogramChart').getContext('2d');
    histogramChart = new Chart(ctx, {
        type: 'bar',
        data: { labels: [], datasets: [] },
        options: {
            responsive: true,
            maintainAspectRatio: false, // fill the fixed-height .chart-panel
            animation: { duration: 0 },
            scales: {
                xAxes: [{
                    ticks: {
                        maxTicksLimit: 8,
                        autoSkip: true,
                        maxRotation: 0,
                        minRotation: 0
                    },
                    scaleLabel: { display: true, labelString: 'Person count' }
                }],
                yAxes: [{
                    ticks: { beginAtZero: true, precision: 0, maxTicksLimit: 5 },
                    scaleLabel: { display: true, labelString: 'Frames' }
                }]
            }
        }
    });

    if (window.ResizeObserver) {
        histogramChartResizeObserver = new ResizeObserver(fitHistogramChart);
        histogramChartResizeObserver.observe(ctx.canvas.parentNode);
    }
    window.addEventListener('resize', fitHistogramChart);
    requestAnimationFrame(fitHistogramChart);
}

// The legacy single-camera datasets: raw series + rolling average.
function singleDatasets() {
    return [
        {
            label: 'Person count',
            data: [],
            borderColor: 'rgba(75, 192, 192, 1)',
            backgroundColor: 'rgba(75, 192, 192, 0.2)',
            borderWidth: 1,
            pointRadius: 2,
            fill: false
        },
        {
            label: 'Rolling average (' + SMOOTHING + ')',
            data: [],
            borderColor: 'rgba(230, 126, 34, 1)',
            borderWidth: 2,
            pointRadius: 0,
            fill: false
        }
    ];
}

// Function to build/refresh the chart. The Chart is created once and then
// updated in place (never destroyed), so the canvas geometry doesn't reflow
// every second as new samples arrive.
function renderChart(rows) {
    // Focus on the most recent samples so old runs don't compress the timeline.
    const recent = rows.slice(-WINDOW_SAMPLES);
    const labels = recent.map(entry => formatTime(parseTimestamp(entry.timestamp)));
    const counts = recent.map(entry => entry.personCount);
    const smoothed = rollingMean(counts, SMOOTHING);

    ensureChart();
    if (chartMode !== 'single') {
        chart.data.datasets = singleDatasets();
        Object.keys(cameraDatasets).forEach(camera => delete cameraDatasets[camera]);
        chartMode = 'single';
    }

    // Update existing chart data in place.
    chart.data.labels = labels;
    chart.data.datasets[0].data = counts;
    chart.data.datasets[1].data = smoothed;
    chart.update();
}

// Multi-camera view: one raw series per camera, reconciled each fetch. Existing
// dataset objects are reused (never recreating the Chart) so a camera appearing
// or disappearing doesn't reset the canvas or the ResizeObserver.
function renderMultiChart(rows) {
    ensureChart();
    if (chartMode !== 'multi') {
        chart.data.datasets = [];
        Object.keys(cameraDatasets).forEach(camera => delete cameraDatasets[camera]);
        chartMode = 'multi';
    }

    const cameras = camerasInOrder(rows);
    const timestamps = recentTimestamps(rows);
    const labels = timestamps.map(timestamp => formatTime(parseTimestamp(timestamp)));

    const countsByCamera = {};
    rows.forEach(row => {
        if (!countsByCamera[row.camera]) {
            countsByCamera[row.camera] = {};
        }
        countsByCamera[row.camera][row.timestamp] = row.personCount;
    });

    cameras.forEach((camera, index) => {
        let dataset = cameraDatasets[camera];
        if (!dataset) {
            dataset = {
                label: camera,
                data: [],
                borderColor: CAMERA_COLORS[index % CAMERA_COLORS.length],
                backgroundColor: 'transparent',
                borderWidth: 1,
                pointRadius: 2,
                fill: false,
                spanGaps: true // join a camera's points across other cameras' slots
            };
            cameraDatasets[camera] = dataset;
        }
        dataset.borderColor = CAMERA_COLORS[index % CAMERA_COLORS.length];
        dataset.data = timestamps.map(timestamp => {
            const perCamera = countsByCamera[camera];
            return timestamp in perCamera ? perCamera[timestamp] : null;
        });
    });

    // Drop datasets for cameras that vanished from the CSV.
    Object.keys(cameraDatasets).forEach(camera => {
        if (!cameras.includes(camera)) {
            delete cameraDatasets[camera];
        }
    });

    chart.data.labels = labels;
    chart.data.datasets = cameras.map(camera => cameraDatasets[camera]);
    chart.update();
    return cameras;
}

// Telemetry datasets: with the split schema, service time and queue wait are
// two independent series (fixed colours, one point per telemetry row).
function splitProcessingDatasets() {
    return [
        {
            label: 'service (ms)',
            data: [],
            borderColor: SERVICE_COLOR,
            backgroundColor: 'transparent',
            borderWidth: 1,
            pointRadius: 2,
            fill: false
        },
        {
            label: 'queue wait (ms)',
            data: [],
            borderColor: QUEUE_COLOR,
            backgroundColor: 'transparent',
            borderWidth: 1,
            pointRadius: 2,
            fill: false
        }
    ];
}

// Fallback for older single-time telemetry: one processing (ms) series.
function legacyProcessingDatasets() {
    return [
        {
            label: 'processing (ms)',
            data: [],
            borderColor: SERVICE_COLOR,
            backgroundColor: 'transparent',
            borderWidth: 1,
            pointRadius: 2,
            fill: false
        }
    ];
}

// Per-frame telemetry over the rolling window: one point per row (rows are
// sequential across cameras, so no per-camera grouping here). The 5-column
// schema draws service vs queue wait; the legacy schema keeps a single
// processing (ms) series. The Chart instance is reused; only the datasets are
// rebuilt when the schema flips.
function renderProcessingChart(rows) {
    ensureProcessingChart();

    const recent = rows.slice(-WINDOW_SAMPLES);
    const labels = recent.map(row => formatTime(parseTimestamp(row.timestamp)));
    const split = recent[0].serviceMs !== undefined;
    const mode = split ? 'split' : 'single';

    if (processingChartMode !== mode) {
        processingChart.data.datasets = split ? splitProcessingDatasets() : legacyProcessingDatasets();
        processingChartMode = mode;
    }

    processingChart.data.labels = labels;
    if (split) {
        processingChart.data.datasets[0].data = recent.map(row => row.serviceMs);
        processingChart.data.datasets[1].data = recent.map(row => row.queueMs);
    } else {
        processingChart.data.datasets[0].data = recent.map(row => row.processingMs);
    }
    processingChart.update();
}

// Person-count distribution over the rolling window: bin the most recent
// WINDOW_SAMPLES rows by integer count, zoomed to the observed range (min..max)
// so a high-count scene is not squeezed against the right edge by an empty
// 0..max span. Both row shapes (legacy {timestamp, personCount} and multi
// {timestamp, camera, personCount}) aggregate into one distribution. Empty
// input yields an empty histogram.
function renderHistogram(rows) {
    ensureHistogramChart();

    const recent = rows.slice(-WINDOW_SAMPLES);
    const counts = recent.map(row => row.personCount).filter(count => !Number.isNaN(count));

    const labels = [];
    const frequencies = [];
    if (counts.length > 0) {
        const minObserved = Math.min(...counts);
        const maxObserved = Math.max(...counts);
        for (let value = minObserved; value <= maxObserved; value++) {
            labels.push(String(value));
            frequencies.push(counts.filter(count => count === value).length);
        }
    }

    histogramChart.data.labels = labels;
    histogramChart.data.datasets = [{
        label: 'Frames',
        data: frequencies,
        backgroundColor: 'rgba(75, 192, 192, 0.6)',
        borderColor: 'rgba(75, 192, 192, 1)',
        borderWidth: 1
    }];
    histogramChart.update();
}

// Show/hide the telemetry panel; hidden when processing.csv is missing/empty.
function setProcessingPanel(visible) {
    const panel = document.getElementById('processingPanel');
    if (panel) {
        panel.hidden = !visible;
    }
}

// Distinct camera ids in order of first appearance.
function camerasInOrder(rows) {
    const seen = new Set();
    const cameras = [];
    rows.forEach(row => {
        if (!seen.has(row.camera)) {
            seen.add(row.camera);
            cameras.push(row.camera);
        }
    });
    return cameras;
}

// Sorted distinct timestamps (the shared x-axis), bounded to the window.
function recentTimestamps(rows) {
    const unique = Array.from(new Set(rows.map(row => row.timestamp)));
    unique.sort();
    return unique.slice(-WINDOW_SAMPLES);
}

// Refresh the per-camera frame grid: one auto-reloading tile per camera. Tiles
// for vanished cameras are dropped; a 404 on a single tile must not break the
// page (the error handler is deliberately empty).
function renderFrames(cameras) {
    const container = document.getElementById('frames');
    if (!container) {
        return;
    }

    // 2-3 streams stack in one column (a vertical strip, not a wide row);
    // 4 or more tile two-up (a 2x2 block for four).
    const twoUp = cameras.length >= 4;
    container.style.gridTemplateColumns = twoUp
        ? 'repeat(2, minmax(0, 1fr))'
        : 'minmax(0, 1fr)';
    container.classList.toggle('cols-2', twoUp);

    const wanted = new Set(cameras);
    Array.from(container.children).forEach(tile => {
        if (!wanted.has(tile.dataset.camera)) {
            tile.remove();
        }
    });

    cameras.forEach(camera => {
        let image = container.querySelector('img[data-camera="' + camera + '"]');
        if (!image) {
            image = document.createElement('img');
            image.dataset.camera = camera;
            image.alt = 'Camera ' + camera;
            image.addEventListener('error', () => {});
            container.appendChild(image);
        }
        image.src = 'frames/' + camera + '.jpg?' + Date.now();
    });
}

// Toggle between the single two-panel layout and the multi-camera view. In
// multi mode the single legacy frame is dropped and the frame grid is shown.
function setCameraView(hasCamera, cameras) {
    document.body.classList.toggle('multi', hasCamera);
    const image = document.getElementById('reloadImage');

    if (hasCamera) {
        if (image) {
            image.removeAttribute('src'); // stop polling the legacy frame
        }
        renderFrames(cameras);
        return;
    }

    const container = document.getElementById('frames');
    if (container) {
        container.innerHTML = '';
    }
    if (image && image.getAttribute('src') === null) {
        image.src = 'processed_frame.jpg';
    }
}

// Rolling (trailing) mean of `values` over `width` samples.
function rollingMean(values, width) {
    return values.map((_, index) => {
        const from = Math.max(0, index - width + 1);
        const slice = values.slice(from, index + 1);
        return slice.reduce((sum, value) => sum + value, 0) / slice.length;
    });
}

// Parse a "YYYY-MM-DD HH:mm:ss" timestamp. The CSV is written by the Azure
// function host, whose clock is UTC; Date.UTC keeps the instant absolute so the
// browser displays it in the viewer's local time (no manual hour offset).
function parseTimestamp(timestampStr) {
    if (!timestampStr || timestampStr.trim() === '') {
        return null;
    }
    const [dateStr, timeStr] = timestampStr.trim().split(' ');
    const [year, month, day] = dateStr.split('-').map(Number);
    const [hours, minutes, seconds] = timeStr.split(':').map(Number);
    return new Date(Date.UTC(year, month - 1, day, hours, minutes, seconds));
}

function formatTime(date) {
    if (date === null) {
        return '';
    }
    return date.toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    });
}

// Newest timestamp in the file. Multi-camera rows are interleaved, so the last
// row is not necessarily the most recent.
function newestTimestamp(rows) {
    let newest = null;
    rows.forEach(row => {
        if (newest === null || row.timestamp > newest) {
            newest = row.timestamp;
        }
    });
    return newest;
}

// Show when the newest sample was recorded, so a stalled streamer is obvious.
// The age comes from the HTTP headers (both server clock), which avoids any
// dependency on the viewer's timezone or clock.
function updateLastUpdate(rows, lastModified, serverDate, hasCamera) {
    const element = document.getElementById('lastUpdate');
    if (!element) {
        return;
    }
    if (rows.length === 0) {
        element.textContent = 'Last update: no data yet';
        element.className = 'status stale';
        return;
    }
    const lastTimestamp = hasCamera ? newestTimestamp(rows) : rows[rows.length - 1].timestamp;
    let ageText = '';
    if (lastModified) {
        const modified = new Date(lastModified).getTime();
        const now = serverDate ? new Date(serverDate).getTime() : Date.now();
        const ageSeconds = Math.max(0, Math.round((now - modified) / 1000));
        ageText = ` (${ageSeconds}s ago)`;
        element.className = ageSeconds <= 15 ? 'status ok' : 'status stale';
    }
    element.textContent = `Last update: ${lastTimestamp}${ageText}`;
}

// Function to fetch new data and reload the chart
function fetchDataAndReloadChart() {
    // Fetch and process the CSV file (no-store so the headers stay fresh)
    fetch('database.csv', { cache: 'no-store' })
        .then(response => {
            const lastModified = response.headers.get('Last-Modified');
            const serverDate = response.headers.get('Date');
            return response.text().then(csv => ({ csv, lastModified, serverDate }));
        })
        .then(({ csv, lastModified, serverDate }) => {
            const parsed = parseCSV(csv);
            if (parsed.hasCamera) {
                const cameras = renderMultiChart(parsed.rows);
                setCameraView(true, cameras);
            } else {
                renderChart(parsed.rows);
                setCameraView(false, []);
            }
            renderHistogram(parsed.rows);
            updateLastUpdate(parsed.rows, lastModified, serverDate, parsed.hasCamera);
        })
        .catch(error => {
            console.error('Error:', error);
            updateLastUpdate([], null, null, false);
        });
}

// Fetch the per-frame telemetry CSV in the same tick as the counts CSV. A
// missing/empty/unparseable file keeps the panel hidden, so the counts view is
// unaffected; the serverless $web site serves processing.csv too (the function
// writes it), so the panel is populated there as well.
function fetchProcessingData() {
    fetch('processing.csv', { cache: 'no-store' })
        .then(response => (response.ok ? response.text() : ''))
        .then(csv => {
            if (!csv || csv.trim() === '') {
                setProcessingPanel(false);
                return;
            }
            const rows = parseProcessingCSV(csv);
            if (rows === null || rows.length === 0) {
                setProcessingPanel(false);
                return;
            }
            setProcessingPanel(true);
            renderProcessingChart(rows);
        })
        .catch(() => {
            setProcessingPanel(false);
        });
}

// Add a cache-busting timestamp without growing the query string each tick.
function addTimestampToUrl(url) {
    const base = url.split('?')[0];
    return base + '?' + new Date().getTime();
}

// Function to reload the single frame and the data every second. In multi mode
// the frame grid is refreshed by renderFrames instead.
function reloadImage() {
    setInterval(function () {
        if (!document.body.classList.contains('multi')) {
            const imageElement = document.getElementById('reloadImage');
            imageElement.src = addTimestampToUrl(imageElement.src);
        }
        fetchDataAndReloadChart();
        fetchProcessingData();
    }, 1000); // 1000 milliseconds = 1 second
}

// Draggable divider between the charts and the video stage. Sets the `--chart-w`
// CSS variable (a percentage of the dashboard width) so both sides re-flow; the
// charts' ResizeObserver re-fits the canvases automatically. The ratio is
// remembered across reloads. Pointer events cover mouse and touch.
function setupSplitter() {
    const dashboard = document.querySelector('.dashboard');
    const splitter = document.getElementById('splitter');
    if (!dashboard || !splitter) {
        return;
    }

    const MIN = 15;
    const MAX = 60;
    let dragging = false;

    function applyRatio(percent) {
        const clamped = Math.min(MAX, Math.max(MIN, percent));
        dashboard.style.setProperty('--chart-w', clamped + '%');
        return clamped;
    }

    const saved = parseFloat(localStorage.getItem('chartWidth'));
    if (!Number.isNaN(saved)) {
        applyRatio(saved);
    }

    function onPointerMove(event) {
        if (!dragging) {
            return;
        }
        const rect = dashboard.getBoundingClientRect();
        applyRatio(((event.clientX - rect.left) / rect.width) * 100);
    }

    function endDrag() {
        if (!dragging) {
            return;
        }
        dragging = false;
        splitter.classList.remove('dragging');
        localStorage.setItem(
            'chartWidth',
            getComputedStyle(dashboard).getPropertyValue('--chart-w').trim()
        );
    }

    splitter.addEventListener('pointerdown', event => {
        dragging = true;
        splitter.classList.add('dragging');
        try {
            splitter.setPointerCapture(event.pointerId);
        } catch (error) {
            // Synthetic/unsupported pointer: dragging still works via pointermove.
        }
        event.preventDefault();
    });
    splitter.addEventListener('pointermove', onPointerMove);
    splitter.addEventListener('pointerup', endDrag);
    splitter.addEventListener('pointercancel', endDrag);

    // Keyboard: left/right arrows nudge the divider.
    splitter.addEventListener('keydown', event => {
        const current = parseFloat(getComputedStyle(dashboard).getPropertyValue('--chart-w')) || 30;
        if (event.key === 'ArrowLeft') {
            applyRatio(current - 2);
            event.preventDefault();
        } else if (event.key === 'ArrowRight') {
            applyRatio(current + 2);
            event.preventDefault();
        }
    });
}

// Call the reloadImage function to start reloading the image
reloadImage();

// Fetch the telemetry once right away so the processing panel appears without
// waiting a full tick (the counts fetch keeps its 1 s cadence).
fetchProcessingData();

setupSplitter();
