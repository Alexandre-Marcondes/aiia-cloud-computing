#!/usr/bin/env python3
"""Render the SLS Part 3 serverless architecture diagram.

The architecture is declared in Python with the ``diagrams`` package (a Graphviz
backend) and rendered to ``docs/architecture.png``.
Requires the Graphviz ``dot`` binary and the ``diagrams`` package:

    pip install -e ".[docs]"
    venv/bin/python scripts/build_architecture_diagram.py
"""

import os
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.azure.compute import FunctionApps
from diagrams.azure.ml import CognitiveServices
from diagrams.azure.storage import BlobStorage
from diagrams.onprem.client import Users
from diagrams.onprem.compute import Server

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "docs" / "architecture"
ENV_FILE = REPO_ROOT / ".env"


def load_dotenv() -> None:
    """Load the repo-root .env (gitignored) into os.environ, if present.

    Mirrors ``deploy/_env.sh``: the repo-root .env is the single source of the
    cloud resource names, shared with the deploy scripts. Values already present
    in the environment are left alone.
    """
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def required(name: str) -> str:
    """Return a required resource name, or stop with an actionable message."""
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"{name} is not set -- add it to {ENV_FILE} (copy .env.example) or export it."
        )
    return value

GRAPH_ATTR = {"fontsize": "12", "splines": "ortho", "ranksep": "1.4", "nodesep": "0.7"}


def build():
    """Declare and render the Part 3 architecture diagram."""
    load_dotenv()
    rg = required("RG")
    storage = required("STORAGE")
    func = required("FUNC")
    vision_name = required("VISION")
    with Diagram(
        "SLS Part 3 — serverless frame processing (France Central)",
        filename=str(OUTPUT),
        outformat=["png"],
        show=False,
        direction="LR",
        graph_attr=GRAPH_ATTR,
    ):
        laptop = Server("local_stream.py\n1 frame / 0.5 s")

        with Cluster(f"Azure — RG {rg} (France Central)"):
            with Cluster(f"Storage account {storage}"):
                raw = BlobStorage("container: raw\n(private)")
                web = BlobStorage("container: $web\n(public static site)")
            function = FunctionApps(f"Function App: {func}\nprocess_frame (blob trigger)")
            vision = CognitiveServices(f"AI Vision: {vision_name}\nComputerVision S1")

        browser = Users("Browser\nstatic site + Chart.js")

        laptop >> Edge(label="upload JPEG, 0.5 s") >> raw
        raw >> Edge(label="BlobCreated raw/*", style="dashed") >> function
        function >> Edge(label="analyze people") >> vision
        vision >> Edge(label="bounding boxes", style="dashed") >> function
        function >> Edge(label="database.csv + processed_frame.jpg") >> web
        web >> Edge(label="poll, 1 s") >> browser


if __name__ == "__main__":
    build()
    print(f"wrote {OUTPUT}.png")
