# serverless/

Azure Function App source for **Part 3** (serverless frame processing), deployed to the existing
Flex Consumption app `<function-app-name>` (Python). See [`../docs/architecture.md`](../docs/architecture.md)
for the full architecture.

- `function_app.py` — the `process_frame` blob trigger (v4 programming model), scoped to
  `raw/{name}` on the `DATA_STORAGE` connection. It reads the uploaded JPEG, calls Azure AI Vision
  (`vision.analyze_people`, which drops boxes below `VISION_MIN_CONFIDENCE`, default 0.30, so a busy
  scene does not report a flood of low-confidence false positives), draws the boxes
  (`render.draw_boxes`), writes `processed_frame.jpg` and appends `database.csv` into the `$web`
  container (`blob_transport`), then deletes the raw blob.
- `host.json` — Functions host configuration (extension bundle, logging).
- `requirements.txt` — function bundle dependencies (`azure-functions`, `azure-storage-blob`,
  `requests`, `Pillow`).

`function_app.py` imports the shared, dependency-light units from `src/` (`blob_transport`,
`csv_log`, `render`, `vision`); the deployment bundle copies those next to it, so nothing is
duplicated. See [`../src/AGENTS.md`](../src/AGENTS.md) for the unit descriptions.
