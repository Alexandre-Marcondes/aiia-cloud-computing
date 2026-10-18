# deploy/

Deployment artifacts for the Azure VM (Part 2) and the serverless pipeline (Part 3). Nothing here runs
automatically; these are copied or applied by hand during deployment.

**Configuration.** Every script reads its cloud resource identifiers and machine-specific settings
from a gitignored repo-root `.env`, loaded by `_env.sh`; a value already exported in the environment
overrides the file, so a one-off target change is `VM_HOST=1.2.3.4 deploy/sync.sh`. There are no
baked-in defaults — a script whose required variable is unset stops with a message naming it. Run
`cp .env.example .env` and fill it in before using anything here. `.env.example` holds placeholders
only; never commit real identifiers.

- `sync.sh` — pushes only the runtime source to the VM over SSH with `rsync` (no git credentials
  needed on the VM). Excludes `.git`, `venv`, `data`, `models`, caches, `*.pt`, and the dev-only
  `docs/`/`tests/`/`scripts/`/`*.md`; `--delete` keeps the remote a strict mirror while protecting the
  excluded paths. `--web` also publishes `web/` to `/var/www/html`, excluding the receiver's generated
  `database.csv`/`processed_frame.jpg`/`plot.png` and the per-camera `frames/` directory so `--delete`
  can't wipe them. `--dry-run` previews. The VM host/user/key/paths are overridable via
  `VM_HOST`/`VM_USER`/`VM_KEY`/`VM_DIR`/`WEB_ROOT`.
- `reset_vm_outputs.sh` — deletes the receiver's runtime outputs (`database.csv`, `processing.csv`,
  `processed_frame.jpg`, `frames/`) from the VM document root so a new run starts with empty CSVs and
  fresh headers. Arguments: `<ssh-key-path> <user@host>` (overridable `WEB_ROOT`). The receiver keeps
  running and recreates each file on the next frame — clearing `processing.csv` is what makes a
  telemetry-schema change take effect.
- `reset_serverless.sh` — clears the serverless pipeline's runtime output so a new run starts from an
  empty site: deletes `raw/*`, `$web/database.csv`, `$web/processing.csv`, `$web/processed_frame.jpg`
  and `$web/frames/*`; the static files (`index.html`, `style.css`, `script.js`, `not_found.html`) are kept. Only
  blob deletions — no infrastructure. Overridable `STORAGE`, `RG`, `WEB_CONTAINER`, `RAW_CONTAINER`.
- `provision_part3.sh` — T11 provisioning/audit script for the Part 3 serverless infrastructure.
  `audit` (read-only) prints the resource inventory — storage account + `raw`/`$web` containers, AI
  Vision endpoint, Function App setting **names** (never secret values) and the `${STORAGE}-raw`
  Event Grid system topic — plus the full JSON of the `raw/`-scoped subscription. `create` (gated
  behind `--yes`) ensures the containers, the system topic (`Microsoft.Storage.StorageAccounts`) and
  the `raw-blob-created` `BlobCreated` subscription, whose filter (`raw/` prefix + `.jpg` suffix, no
  recursion) delivers to the Function App's blobs-extension webhook (host derived at runtime).
  `--dry-run`/`-n` prints every command, including the `create` ones, and makes no Azure call;
  `--help`/`-h` prints usage. Overridable `STORAGE`, `RG`, `FUNC`, `VISION`, `SUBS`, `TOPIC`.
- `deploy_web.sh` — publishes the static frontend to the serverless `$web` container: uploads
  `web/index.html`, `web/style.css`, `web/script.js`, and `web/not_found.html` one explicit file at a
  time with `az storage blob upload --overwrite --auth-mode key` (never `upload-batch`, never
  `--delete`, so the pipeline's runtime blobs in `$web` are left intact). The `$web` analogue of
  `sync.sh --web`. `--dry-run`/`-n` prints the upload commands and runs nothing; `--help`/`-h` prints
  usage. Overridable `STORAGE`, `RG`, `WEB_CONTAINER`, `SRC`.
- `setup_vm.sh` — idempotent provisioning script, run on the VM from the checkout root
  (`bash deploy/setup_vm.sh`). Adds swap, installs the system/OpenCV packages, builds the venv,
  installs CPU PyTorch + the project, and smoke-tests detection. It then renders
  `deploy/sls-receiver.service` with this machine's user/paths and installs it as a systemd unit
  (`--unit-only` does just that step). Safe to re-run.
- `measure.sh` — Part 2.5 measurement harness, run on the VM. Samples the receiver's CPU time
  (`systemctl`), cgroup memory, and NIC counters around a load window and prints the deltas;
  `--self-load` drives the load itself via `src/load_test.py`, otherwise it samples an externally
  generated load (`--seconds`).
- `measure_part3.sh` — Part 3.6 read-only metrics collector (run from anywhere with `az` logged in):
  queries the deployed pipeline's server-side telemetry for a window (`--minutes`) — response time
  from Log Analytics, and compute/AI/storage/event-delivery metrics from Azure Monitor — and prints a
  consolidated report. It changes nothing on Azure and pairs with `src/measure_serverless.py` (the
  client-side probe). Cost is read manually from Portal Cost Management. See `docs/performance.md`.
- `cost.sh` — read-only monetary-cost report for the two project resource groups. `az consumption`
  returns null costs on this student subscription, so it queries the Cost Management REST API
  (`Microsoft.CostManagement/query`, `ActualCost`/EUR) directly: per-day totals plus a per-service
  breakdown for a window (`--from`/`--to`, default the current month through tomorrow; `--rg`
  selects a group, defaulting to the `RGS` list in `.env`). Heads-up: the AI Vision (Foundry
  Tools) meter **posts with a multi-day lag**, so a window's Vision cost appears a few days later —
  re-run the same window to pick it up. Overridable `RGS`, `FROM`, `TO`, `VENV`, `SUBS`.
- `sweep_vm.sh` — Part 4.2 sweep driver: for each N in `--cameras` it starts `measure.sh "vm-N"` on
  the VM over SSH (host/user/key/dir overridable via `VM_HOST`/`VM_USER`/`VM_KEY`/`VM_DIR`, as in
  `sync.sh`) while the local fleet (`local_stream.py --cameras N --interval I --seconds W
  --cloud-url …`) streams for `--seconds`; both outputs are teed to `data/sweeps/vm-N.txt` (`--out`
  overrides) and a one-line summary is printed per N. The receiver's per-N `processing.csv` (and
  `database.csv`) are scp'd to `data/sweeps/vm-N-processing.csv` as the committed-style
  response-time evidence (a missing file is tolerated). `--dry-run` prints the exact SSH/fleet
  command per N and touches nothing.
- `sweep_serverless.sh` — Part 4.3 sweep driver: for each N the fleet uploads to `--raw-container`
  for `--seconds`, then `measure_part3.sh --minutes` (default derived from the window) collects the
  server-side metrics; everything is teed to `data/sweeps/serverless-N.txt`. Each N resets `raw/*`,
  `$web/database.csv` and `$web/processing.csv`, then downloads `$web/processing.csv` to
  `data/sweeps/serverless-N-processing.csv` as the per-frame response-time evidence (a missing blob
  is tolerated). The blob connection string is resolved exactly like `stream_serverless.sh` (from
  `$DATA_STORAGE` or `az`, read-only) and `--dry-run` never calls `az` or runs the fleet.
- `stream_vm.sh` — Part 2 sender, the VM analogue of `stream_serverless.sh`: samples the source video
  in real time every `--interval` s and uploads each frame to the VM receiver. Because the NSG does
  not expose :8000, it opens an SSH local-forward (`localhost:LOCAL_PORT` → the VM's `127.0.0.1:8000`)
  and closes it on exit (Ctrl-C); it reuses a forward already open on the port. `--url` targets a
  different receiver (a direct public IP once NSG 8000 is open) and skips the tunnel; `--no-tunnel`
  reuses an existing forward. `--cameras`/`--camera-id`/`--phase-offset`/`--fast`/`--max-samples`/
  `--display` mirror the serverless sender. The receiver must already run (`sls-receiver.service`).
  `--dry-run`/`-n` prints the tunnel + streamer commands and runs nothing. Overridable: `VM_HOST`,
  `VM_USER`, `VM_KEY`, `LOCAL_PORT`, `VENV`.
- `stream_serverless.sh` — Part 3 sender: samples the source video in real time every `--interval`
  seconds and uploads each frame to the `raw` container via `src/local_stream.py`
  (`--blob-connection-string`). Resolves the connection string from `$DATA_STORAGE` or Azure
  (read-only). Loops until Ctrl-C; `--fast --max-samples N` gives a quick burst. The camera id
  defaults to empty (the sender's legacy `cam`); `--camera-id` sets the base and `--cameras N`
  drives N pseudo-cameras `<base>-1`..`<base>-N` (then `--max-samples` is per camera and `--fast`
  is rejected); `--phase-offset S` makes each camera sample the clip `S` seconds behind the previous.
- `build_function.sh` — assembles the VS Code deploy bundle: idempotently copies `serverless/`
  (`function_app.py`, `host.json`, `requirements.txt`) plus the shared `src/` units
  (`blob_transport.py`, `csv_log.py`, `render.py`, `vision.py`) into `build/function/`, drops any
  stale `.venv`, scaffolds a minimal `.vscode/` (so the extension recognizes the folder and skips the
  re-initialize prompt), writes `.funcignore`, and prints the bundle contents. Re-run after editing
  those files, then deploy from VS Code by opening `build/function/`.
- `deploy_function.sh` — builds the bundle (`build_function.sh`), zips `build/function/` (excluding
  `.vscode`/`.funcignore`), and deploys it to the Function App with
  `az functionapp deployment source config-zip --build-remote true` (Azure runs the Oryx
  `pip install`). The VS Code-free deploy path. `--dry-run` builds + zips only. Overridable:
  `RG`, `FUNC`, `BUILD_DIR`, `ZIP`.
- `sls-receiver.service` — systemd unit that runs `src/cloud_receiver.py` as a long-lived service on
  the VM. It binds port 8000, writes `database.csv` / `processed_frame.jpg` / `plot.png` into the
  Apache document root (`/var/www/html`), and restarts on failure — so the receiver survives SSH
  logout and VM reboots. It is a **template**, not a ready-made unit: `setup_vm.sh` renders its
  `@SLS_USER@`/`@SLS_WORKDIR@`/`@SLS_VENV@`/`@WEB_ROOT@` placeholders from the VM's actual layout and
  installs the result at `/etc/systemd/system/sls-receiver.service`, so no host path is committed.
  `EnvironmentFile=` was rejected for this: systemd expands variables only inside `ExecStart=`, so
  `User=`/`WorkingDirectory=` must hold literal values. Re-render any time with
  `bash deploy/setup_vm.sh --unit-only`.

The static `web/` page and the unit's output files share `/var/www/html`: Apache serves the page and
the frontend polls those files, so no API or database is involved.
