"""Frozen entry point: browser lookup is anchored to the distribution folder."""
import os
import sys
from pathlib import Path

from relay.__main__ import main

if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(sys.executable).resolve().parent / "browsers")
    main()
