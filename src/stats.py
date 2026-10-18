"""Running statistics over sampled person counts."""


class PersonStats:
    """Accumulates per-sample person counts and computes running statistics."""

    def __init__(self):
        self.counts = []

    def add(self, count):
        """Record one sampled person count."""
        self.counts.append(count)

    @property
    def samples(self):
        """Number of sampled frames processed so far."""
        return len(self.counts)

    @property
    def total(self):
        """Total persons detected across all samples."""
        return sum(self.counts)

    @property
    def mean(self):
        """Mean persons per sampled frame."""
        return self.total / self.samples if self.samples else 0.0

    @property
    def min(self):
        """Minimum persons per sampled frame."""
        return min(self.counts) if self.counts else 0

    @property
    def max(self):
        """Maximum persons per sampled frame."""
        return max(self.counts) if self.counts else 0

    def summary(self):
        """Return all running statistics as a dict."""
        return {
            "samples": self.samples,
            "total": self.total,
            "mean": self.mean,
            "min": self.min,
            "max": self.max,
        }
