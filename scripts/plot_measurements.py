#!/usr/bin/env python3
"""Ad-hoc plots for the 2026-10-17 remeasurement reports.

Reads the local captures in ``data/sweeps/`` (gitignored) and writes PNGs next to
the reports in ``docs/measurements/``. Run with the project venv:

    venv/bin/python scripts/plot_measurements.py

It degrades gracefully: any N whose capture is missing is simply skipped.
"""

import csv
import statistics
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SWEEPS = REPO / "data" / "sweeps"
OUT = REPO / "docs" / "measurements"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update(
    {
        "figure.dpi": 130,
        "font.size": 10,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)
C_SENT, C_PROC, C_Q, C_S = "#4c72b0", "#dd8452", "#c44e52", "#55a868"


def _rows(prefix, n):
    path = SWEEPS / f"{prefix}-{n}-processing.csv"
    if not path.exists():
        return []
    return list(csv.DictReader(path.open()))


def _sent(prefix, n):
    path = SWEEPS / f"{prefix}-{n}.txt"
    if not path.exists():
        return None
    total = 0
    for line in path.read_text().splitlines():
        if line.startswith("camera ") and ": sent " in line:
            total += int(line.rsplit(" ", 1)[1])
    return total or None


def _num(text):
    return float(text)


# --------------------------------------------------------------------------
# 1. Sender capacity (shared)
# --------------------------------------------------------------------------
def plot_sender_capacity():
    offered = [128, 256, 512, 2560, 5120]
    achieved = [128.2, 256.3, 512.1, 2460.0, 2234.7]
    fig, ax = plt.subplots(figsize=(7.0, 4.4))
    lim = [1, 8000]
    ax.plot(lim, lim, "--", color="0.5", lw=1, label="offered = achieved")
    ax.scatter(offered, achieved, s=45, color=C_SENT, zorder=3, label="sender (local sink)")
    ax.axvline(3.2, color=C_Q, lw=1.2, ls=":")
    ax.axvline(28.8, color=C_PROC, lw=1.2, ls=":")
    ax.annotate("VM sweep\nmax 3.2 fps", xy=(3.2, 1.2), xytext=(4.2, 1.2), color=C_Q, fontsize=8)
    ax.annotate(
        "serverless sweep\nmax 28.8 fps", xy=(28.8, 1.2), xytext=(38, 1.2), color=C_PROC, fontsize=8
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(*lim)
    ax.set_ylim(*lim)
    ax.set_xlabel("offered rate (frames/s)")
    ax.set_ylabel("achieved rate (frames/s)")
    ax.set_title("Local sender capacity vs. sweep operating points", fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "sender-capacity.png")
    plt.close(fig)


# --------------------------------------------------------------------------
# 2. VM 4.2 per-N
# --------------------------------------------------------------------------
VM_NS = [6, 7, 8, 9, 10, 11, 12, 13, 16]


def plot_vm_n_cameras():
    ns, offered, sent, proc, qmean, smean = [], [], [], [], [], []
    for n in VM_NS:
        rows = _rows("vm", n)
        if not rows:
            continue
        ns.append(n)
        offered.append(n * 12)
        sent.append(_sent("vm", n) or len(rows))
        proc.append(len(rows))
        qmean.append(statistics.mean(_num(r["QueueMs"]) for r in rows))
        smean.append(statistics.mean(_num(r["ServiceMs"]) for r in rows))

    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.2))
    x = range(len(ns))
    pct = [100 * s / o for s, o in zip(sent, offered, strict=True)]
    colors = [C_S if p >= 95 else C_Q for p in pct]
    a.bar(x, pct, width=0.6, color=colors)
    a.axhline(100, color="0.4", ls="--", lw=1)
    a.set_ylim(0, 112)
    a.set_xticks(list(x))
    a.set_xticklabels(ns)
    a.set_xlabel("cameras N")
    a.set_ylabel("frames delivered (% of offered)")
    a.set_title("VM 4.2 — delivery vs. offered load")
    for i, (o, s) in enumerate(zip(offered, sent, strict=True)):
        a.text(i, pct[i] + 1.5, f"{s}/{o}", ha="center", fontsize=7)

    b.plot(ns, qmean, "o-", color=C_Q, label="QueueMs mean")
    b.plot(ns, smean, "s-", color=C_S, label="ServiceMs mean")
    b.set_yscale("log")
    b.set_xlabel("cameras N")
    b.set_ylabel("ms (log)")
    b.set_title("VM 4.2 — queue wait vs. service time")
    b.axvspan(5.5, 6.5, color=C_S, alpha=0.12)
    b.text(6.0, 9000, "N=6\nhealthy", color=C_S, fontsize=8, ha="center")
    b.legend(fontsize=8)

    fig.suptitle("VM Part 4.2 — 1 frame / 5 s per camera (2026-10-17)", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "vm-4.2-n-cameras.png")
    plt.close(fig)


def plot_vm_queue_timeline():
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    for n, color in ((8, C_SENT), (9, C_Q)):
        rows = _rows("vm", n)
        if not rows:
            continue
        ts = [datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S") for r in rows]
        t0 = ts[0]
        el = [(t - t0).total_seconds() for t in ts]
        q = [_num(r["QueueMs"]) for r in rows]
        ax.plot(el, q, ".-", color=color, ms=4, lw=1, label=f"N={n} (QueueMs)")
    ax.set_yscale("symlog", linthresh=1)
    ax.set_xlabel("seconds into the window")
    ax.set_ylabel("QueueMs (symlog)")
    ax.set_title("VM — per-frame queue wait: a stall, not a ramp")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "vm-4.2-queue-timeline.png")
    plt.close(fig)


# --------------------------------------------------------------------------
# 3. Serverless 4.3 per-N + latency
# --------------------------------------------------------------------------
SL_NS = [64, 128, 144, 192]


def _serverless_metrics(n):
    """Parse the Vision success + failed invocations from serverless-N.txt."""
    path = SWEEPS / f"serverless-{n}.txt"
    if not path.exists():
        return None
    vision = vision_ok = failed = None
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("PrimaryResult"):
            parts = s.split()
            if len(parts) >= 8:
                failed = int(parts[3])
        if s.startswith("calls") and "successful" in s:
            vision = int(s.split()[2])
            vision_ok = int(s.split("successful")[1].strip(" ()"))
    return {"vision": vision, "vision_ok": vision_ok, "failed": failed}


def plot_serverless_n_cameras():
    ns, smean, sp95, success, failed = [], [], [], [], []
    for n in SL_NS:
        rows = _rows("serverless", n)
        if not rows:
            continue
        m = _serverless_metrics(n) or {}
        ns.append(n)
        sv = [_num(r["ServiceMs"]) for r in rows]
        smean.append(statistics.mean(sv))
        sp95.append(sorted(sv)[max(0, int(0.95 * len(sv)) - 1)])
        success.append(100 * m["vision_ok"] / m["vision"] if m.get("vision") else 0)
        failed.append(m.get("failed") or 0)

    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.2))
    x = range(len(ns))
    a.bar([i - 0.2 for i in x], smean, width=0.4, color=C_S, label="ServiceMs mean")
    a.bar([i + 0.2 for i in x], sp95, width=0.4, color=C_Q, label="ServiceMs p95")
    a.set_xticks(list(x))
    a.set_xticklabels(ns)
    a.set_xlabel("cameras N")
    a.set_ylabel("ms")
    a.set_title("Serverless 4.3 — per-frame service time")
    a.legend(fontsize=8)

    b.bar(x, success, width=0.5, color=C_SENT, label="Vision success %")
    b.set_ylim(0, 105)
    b.set_xticks(list(x))
    b.set_xticklabels(ns)
    b.set_xlabel("cameras N")
    b.set_ylabel("Vision success %")
    b.set_title("Serverless 4.3 — throttling sets in")
    b2 = b.twinx()
    b2.plot(x, failed, "o-", color=C_Q, label="failed invocations")
    b2.set_ylabel("failed invocations")
    b2.set_ylim(0, max(failed) * 1.18 if failed else 1)
    b2.grid(False)
    for i, s in enumerate(success):
        b.text(i, s + 1, f"{s:.0f}%", ha="center", fontsize=8)
    h1, l1 = b.get_legend_handles_labels()
    h2, l2 = b2.get_legend_handles_labels()
    b.legend(h1 + h2, l1 + l2, fontsize=8, loc="lower left")

    fig.suptitle("Serverless Part 4.3 — 1 frame / 5 s per camera (2026-10-17)", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "serverless-4.3-n-cameras.png")
    plt.close(fig)


def plot_serverless_latency():
    labels = ["min", "median", "mean", "p95"]
    server = [381, 628, 628, 638]  # invocation duration (avg used for median/mean)
    e2e = [820, 951, 964, 1085]  # upload -> visible
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    ax.bar([i - 0.2 for i in x], server, width=0.4, color=C_S, label="server-side invocation")
    ax.bar([i + 0.2 for i in x], e2e, width=0.4, color=C_SENT, label="end-to-end upload→visible")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("ms")
    ax.set_title("Serverless response time — server-side vs. client-observed")
    ax.legend(fontsize=8)
    ax.annotate(
        "≈0.3 s = Event Grid + trigger + poll",
        xy=(2.2, 964),
        xytext=(1.4, 1250),
        fontsize=8,
        arrowprops={"arrowstyle": "->", "color": "0.4"},
    )
    fig.tight_layout()
    fig.savefig(OUT / "serverless-latency.png")
    plt.close(fig)


def main():
    plot_sender_capacity()
    plot_vm_n_cameras()
    plot_vm_queue_timeline()
    plot_serverless_n_cameras()
    plot_serverless_latency()
    for png in sorted(OUT.glob("*.png")):
        print("wrote", png.relative_to(REPO))


if __name__ == "__main__":
    main()
