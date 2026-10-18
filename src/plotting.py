"""Person-count-over-time chart, saved to disk and optionally shown live."""

import os
import sys
from datetime import datetime
from pathlib import Path

from csv_log import TIMESTAMP_FORMAT


def has_display():
    """Best-effort check for an interactive display (Linux/macOS)."""
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY"))


class PlotDisplay:
    """Live chart of person count over time, saved to ``plot_out``.

    Each sample's CSV timestamp is placed on the x-axis (time of day, not a
    sample index). Uses an interactive matplotlib backend when a display is
    available and ``no_display`` is False; otherwise falls back to the headless
    ``Agg`` backend (the plot is still saved to ``plot_out`` on every sample).
    """

    def __init__(self, plot_out, no_display=False):
        import matplotlib

        use_agg = no_display or not has_display()
        if use_agg:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        self.plt = plt
        self.plot_out = Path(plot_out)
        self._interactive = not use_agg
        self.figure = None
        self.axis = None
        self._timestamps = []
        self._counts = []

    def add(self, timestamp, count):
        """Record one sample at ``timestamp`` with ``count`` and re-render."""
        self._timestamps.append(timestamp)
        self._counts.append(count)
        self._render()

    def _render(self):
        """Plot the saved samples by timestamp and save the figure."""
        plt = self.plt
        import matplotlib.dates as mdates

        if self.figure is None:
            self.figure, self.axis = plt.subplots(figsize=(8, 4))
        axis = self.axis
        axis.clear()
        times = [datetime.strptime(t, TIMESTAMP_FORMAT) for t in self._timestamps]
        axis.plot(times, self._counts, marker="o", linestyle="-")
        axis.set_xlabel("Time")
        axis.set_ylabel("Person count")
        axis.set_title("People detected over time")
        axis.set_ylim(bottom=0)
        axis.xaxis.set_major_locator(mdates.AutoDateLocator())
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.figure.autofmt_xdate()
        self.figure.tight_layout()
        self.figure.savefig(self.plot_out)
        if self._interactive:
            plt.draw()
            plt.pause(0.01)

    def close(self):
        """Close the matplotlib figure, if any."""
        if self.figure is not None:
            self.plt.close(self.figure)
            self.figure = None
