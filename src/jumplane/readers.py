"""Usage readings from what the hosts already expose. Only limit fields are read; never prompts or replies.

Claude Code documents `rate_limits` in its status line input. The Codex session log format is undocumented,
so any surprise there means no reading.
"""
from __future__ import annotations

import datetime
import json
import math
import os
import sys
import time
from pathlib import Path

from . import store

CLAUDE_WINDOWS = {"five_hour": 300, "seven_day": 10080}
_TAIL_BYTES = 1_048_576
_STDIN_LIMIT = 4_194_304


def _clean(used, resets):
    numeric = isinstance(used, (int, float)) and not isinstance(used, bool) and 0 <= used <= 100
    timed = isinstance(resets, (int, float)) and not isinstance(resets, bool) and math.isfinite(resets) and resets > 0
    return numeric and timed


def keep(state: dict, pool: str, minutes: int, used, resets, at: float, source: str) -> None:
    """Store a reading unless a newer one for that window is already held."""
    windows = state["readings"].setdefault(pool, {})
    held = windows.get(str(minutes))
    if held is None or at >= held["at"]:
        windows[str(minutes)] = {"used": float(used), "resets_at": float(resets), "at": at, "source": source}


def parse_statusline(data) -> list[tuple[int, float, float]]:
    limits = data.get("rate_limits") if isinstance(data, dict) else None
    found = []
    for key, minutes in CLAUDE_WINDOWS.items():
        window = limits.get(key) if isinstance(limits, dict) else None
        if isinstance(window, dict) and _clean(window.get("used_percentage"), window.get("resets_at")):
            found.append((minutes, window["used_percentage"], window["resets_at"]))
    return found


def _left(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 86400:
        return f"{seconds // 86400}d{seconds % 86400 // 3600}h"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


def statusline(raw: bytes, now=None) -> str:
    """Store what the host sent and return one line. A status line must never fail its host, so every failure is a plain line."""
    now = time.time() if now is None else now
    try:
        windows = parse_statusline(json.loads(raw[:_STDIN_LIMIT]))
    except ValueError:
        windows = []
    if not windows:
        return "jumplane: no limit data from host"
    try:
        with store.locked(wait=0.5):
            state = store.load()
            for minutes, used, resets in windows:
                keep(state, "claude", minutes, used, resets, now, "statusline")
            store.save(state)
    except (store.StoreError, OSError):
        pass
    return " | ".join(f"{'5h' if m == 300 else '7d'} {u:g}% resets {_left(r - now)}" for m, u, r in windows)


def _newest_log(root: Path):
    """Newest session log, walking the dated folders from the newest down, so old history costs nothing."""
    def newest(folder, pattern):
        return sorted(folder.glob(pattern), reverse=True)
    for year in newest(root, "[0-9]*"):
        for month in newest(year, "[0-9]*"):
            for day in newest(month, "[0-9]*"):
                logs = list(day.glob("rollout-*.jsonl"))
                if logs:
                    return max(logs, key=lambda p: p.stat().st_mtime)
    return None


def read_codex(root: Path | None = None) -> list[tuple[int, float, float, float]]:
    """Latest (minutes, used, resets_at, event time) from the Codex log, or nothing."""
    root = root or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    try:
        log = _newest_log(root)
        if log is None:
            return []
        with open(log, "rb") as handle:
            handle.seek(max(0, log.stat().st_size - _TAIL_BYTES))
            lines = handle.read().split(b"\n")
    except OSError:
        return []
    for line in reversed(lines):
        if b'"rate_limits"' not in line:
            continue
        try:
            event = json.loads(line)
            limits = event["payload"]["rate_limits"]
            at = datetime.datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")).timestamp()
            found = []
            for name in ("primary", "secondary"):
                window = limits.get(name)
                if window and isinstance(window.get("window_minutes"), int) and _clean(window.get("used_percent"), window.get("resets_at")):
                    found.append((window["window_minutes"], window["used_percent"], window["resets_at"], at))
            return found
        except (ValueError, KeyError, TypeError, AttributeError):
            return []
    return []


def refresh(state: dict, rules: dict) -> None:
    """Bring Codex readings up to date from the local log. Opens no socket and starts no process."""
    pools = {lane["pool"] for lane in rules["lanes"] if lane["host"] == "codex"}
    if not pools:
        return
    readings = read_codex()
    for pool in pools:
        for minutes, used, resets, at in readings:
            keep(state, pool, minutes, used, resets, at, "codex-log")


def read_stdin() -> bytes:
    return sys.stdin.buffer.read(_STDIN_LIMIT)
