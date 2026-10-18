# data/

Local runtime output — not source; excluded from version control (`data/*`, except this file).

- `database.csv` — person count over time. Legacy schema `Timestamp,Person_Count`
  (e.g. `2026-09-24 19:50:03,0`); camera-tagged runs use `Timestamp,Camera,Person_Count` instead
  (the header is chosen from the row's field count — see `src/csv_log.py`).
- `processed_frame.jpg` — the annotated frame (person bounding boxes drawn).
- `plot.png` — the saved matplotlib chart.
- `people_walking.mp4` — downloaded debug clip (yt-dlp), used locally while the live webcam has no
  pedestrian traffic. Runtime artifact, gitignored.
- `sweeps/` — raw per-`N` output of the Part 4 sweep scripts (`deploy/sweep_vm.sh`,
  `deploy/sweep_serverless.sh`); gitignored. The curated captures are committed under `docs/sweeps/`.

The cloud components write the same CSV/frame contract, plus `processing.csv`
(`Timestamp,Camera,ProcessingMs,QueueMs,ServiceMs`), into their own document root / `$web` container
— not here.
