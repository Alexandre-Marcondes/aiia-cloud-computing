# docs/

Course material and project notes.

- `Practice1.pdf` — the assignment: Smart Lighting System, Parts 1–4 (local, cloud VM, serverless,
  multi-camera) and deliverables.
- `AIIA_Introduction_4x3_EN.pdf` — course intro: grading (70% practical / 30% theory) and deadlines
  (Assignment 1 due 18 Oct; Assignment 2 Docker + Quantum due 25 Oct).
- `Session1.pdf` — Unit 3 lecture: Cloud Computing paradigm, deployment models, service models
  (IaaS/PaaS/SaaS/FaaS), virtualization, containers.
- `Azure documentation 1.pdf` — Azure how-to: Function App (serverless), Storage Account + blob
  containers, static website (`$web`).
- `architecture.md` — design doc for the Part 3 serverless architecture, embedding the generated
  `architecture.png` (rendered by `scripts/build_architecture_diagram.py`).
- `performance.md` — Part 3 measurement reference (Task 3.6): what we measure for detection
  efficiency, monetary cost, and response time, the read-only instruments, and the protocol.

> **Provenance:** the "example process provided by the Teaching Team" cited throughout
> `Practice1.pdf` *is* this repo's starting code — the local capture/detection scripts in `src/`
> (originally `src/grabber.py`, now `local_test_platform.py` + shared modules) plus `web/` — not a
> separate download.
