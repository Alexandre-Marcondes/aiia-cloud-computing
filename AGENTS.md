# Project AGENTS

## What this is

Practice 1 (Cloud Computing Services) of the **AIIA** course: a Smart Lighting System (SLS)
presence sensor that counts people in frames from a fixed public webcam using **YOLOv8**, logs the
counts to CSV, and charts them. Later parts offload the pipeline to Azure (VM, Functions, storage
container).

The human-facing presentation is `README.md`; the full brief is `docs/Practice1.pdf`.

## Layout

Mirrors `README.md`. Details per module:

- `docs/` — course PDFs. See `docs/AGENTS.md`.
- `src/` — capture + detection pipeline. See `src/AGENTS.md`.
- `serverless/` — Azure Function source (Part 3). See `serverless/AGENTS.md`.
- `web/` — static frontend (chart + latest frame). See `web/AGENTS.md`.
- `models/` — YOLO weights, not committed. See `models/AGENTS.md`.
- `data/` — runtime output. See `data/AGENTS.md`.
- `.pre-commit-config.yaml` — ruff hooks run on push. See **Git hooks** below.

## Cloud operations (Azure)

The user performs Azure work **through the Azure Portal UI** — that is the point of the exercise
(learning the platform). An agent's role is to **explain, verify, and unblock**, never to act on the
user's behalf:

- **Explain every `az` command before it runs** — what it does, what it creates/changes, and what it
  costs — so the user can follow and reproduce it in the Portal.
- **Never run a state-changing `az` command** (create/update/delete, deploy, start/stop/deallocate)
  without the user's explicit go-ahead. Read-only inspection (`list`, `show`, `check-name`) is fine.
- **No executive design changes.** Architecture, region, tier, and naming decisions belong to the
  user; propose options and let them choose rather than deciding unilaterally.
- The user drives the Portal. Step in only when asked — to confirm a result looks right or to
  diagnose something they could not get working.

## Environment

- **Always work inside the project virtualenv `venv/`.** Before any work, create one if it is
  missing — `python3 -m venv venv` then `pip install -e .` (add `pip install -e ".[utils]"` for the
  helper scripts). Activate it (`source venv/bin/activate`) or call `venv/bin/python` /
  `venv/bin/pip` directly, and install any further pip packages there — never into the system Python.
- Developed across macOS and Ubuntu/Linux; keep tooling, paths, and commands portable.
- Python ≥ 3.10; dependencies declared in `pyproject.toml`.
- Lint/format: **ruff** — `line-length = 100`, `target-version = py310`, double quotes, rules `E,F,I,UP,B`.

## Git hooks

[`pre-commit`](https://pre-commit.com) runs, **on `git push`** (not on commit): `ruff check` and
`ruff format --check` over `scripts/`, `src/`, `tests/`, and `web/`, plus the unit-test suite
(`pytest`) from the project venv. The hooks are declared in `.pre-commit-config.yaml` (ruff pinned
to the same release as the venv). The git hook is **not active until installed** — run this once per
clone:

```sh
venv/bin/pre-commit install   # installs the pre-push hook (default_install_hook_types)
```

`pre-commit`, `pytest`, and `ruff` are in the `dev` dependency group
(`venv/bin/pip install pre-commit pytest ruff`; see **Environment**). Run the hooks by hand with
`venv/bin/pre-commit run --all-files --hook-stage pre-push`. Bypass them only in an emergency with
`git push --no-verify`.
