"""
Shared logging setup: optional log file + stdout, consistent format for debugging.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_file: str = "", level: int = logging.INFO) -> None:
    """
    Configure root logger: stdout always, and optional file when log_file is set.
    Call from worker and API on startup so both write to the same file when LOG_FILE is set.
    """
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Remove existing handlers so we don't duplicate when called multiple times
    for h in root.handlers[:]:
        root.removeHandler(h)

    # Stdout
    out = logging.StreamHandler(sys.stdout)
    out.setLevel(level)
    out.setFormatter(formatter)
    root.addHandler(out)

    if log_file and log_file.strip():
        path = Path(log_file.strip())
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(formatter)
        root.addHandler(fh)
