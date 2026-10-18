"""Repository-root path helpers shared by the SLS scripts."""

from pathlib import Path

# Repository root, so default paths resolve regardless of the working directory.
REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_path(path):
    """Resolve ``path`` to an absolute path, relative to the repository root.

    Absolute inputs are returned unchanged; relative ones (the CLI defaults) are
    anchored at the repo root so scripts work from any working directory.
    """
    p = Path(path)
    if p.is_absolute():
        return p.resolve()
    return (REPO_ROOT / p).resolve()


def ensure_parent(path):
    """Create the parent directory of ``path`` if it does not exist."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
