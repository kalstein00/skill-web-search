"""Single-owner profile directory with startup cleanup, no request content logs."""
import shutil
import sys
from pathlib import Path
from typing import BinaryIO


class RuntimeDirectory:
    def __init__(self, path: Path):
        self.path = path.absolute()
        self.lock: BinaryIO | None = None

    def __enter__(self):
        self.path.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink() or self.path.is_junction():
            raise RuntimeError("Runtime directory must not be a link.")
        self.lock = (self.path / "server.lock").open("a+b")
        self.lock.seek(0)
        self.lock.write(b"0")
        self.lock.flush()
        self.lock.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.clean()
        except (OSError, RuntimeError):
            self.lock.close()
            raise RuntimeError("Runtime directory is locked or cannot be cleaned.") from None
        return self

    def clean(self):
        for child in self.path.glob("web-relay-request-*"):
            if child.is_symlink() or child.is_junction() or child.resolve().parent != self.path.resolve():
                raise RuntimeError("Unexpected link in runtime directory.")
            if child.is_dir():
                shutil.rmtree(child)

    def __exit__(self, *args):
        try:
            self.clean()
        finally:
            if self.lock is not None:
                self.lock.close()
