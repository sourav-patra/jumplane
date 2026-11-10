"""State folder: one JSON document behind one lock, and an append-only event log."""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path

LOCK_WAIT_SECONDS = 5.0
_EMPTY = {"picks": {}, "requests": {}, "readings": {}, "holds": {}, "probes": {}, "verified": {}}
_thread_lock = threading.RLock()
_depth = threading.local()


class StoreError(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("JUMPLANE_HOME") or Path.home() / ".jumplane")


def _try_lock(fd: int) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def locked(wait: float | None = None):
    """Hold the state lock. A thread that holds it may enter again; waiting is bounded, so a pick cannot hang."""
    with _thread_lock:
        depth = getattr(_depth, "n", 0)
        if depth:
            _depth.n = depth + 1
            try:
                yield
            finally:
                _depth.n = depth
            return
        folder = home()
        folder.mkdir(parents=True, exist_ok=True)
        # The operating system frees this lock when a process dies, so no stale lock can block later picks.
        fd = os.open(folder / "state.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            limit = LOCK_WAIT_SECONDS if wait is None else wait
            deadline = time.monotonic() + limit
            while not _try_lock(fd):
                if time.monotonic() >= deadline:
                    raise StoreError(f"state lock busy after {limit:g} s: {folder / 'state.lock'}")
                time.sleep(0.01)
            _depth.n = 1
            try:
                yield
            finally:
                _depth.n = 0
                _unlock(fd)
        finally:
            os.close(fd)


def load() -> dict:
    path = home() / "state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {}
    except (OSError, ValueError) as exc:
        raise StoreError(f"cannot read {path}: {exc}; fix or remove that file") from exc
    return {**json.loads(json.dumps(_EMPTY)), **state}


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows refuses while a reader or scanner has the target open
            if attempt == 19:
                raise
            time.sleep(0.05)


def save(state: dict) -> None:
    write_atomic(home() / "state.json", json.dumps(state, indent=1, sort_keys=True) + "\n")


def event(kind: str, at: float, **fields) -> None:
    line = json.dumps({"kind": kind, "at": at, **fields}, sort_keys=True)
    with open(home() / "events.jsonl", "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
