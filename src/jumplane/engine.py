"""pick, report, override and holds. Rules and code decide; no model output selects a route. Opens no socket."""
from __future__ import annotations

import json
import math
import re
import secrets
import time

from . import readers, rules as rules_mod, store

OUTCOMES = ("done", "failed", "abandoned", "limit_hit")
REQUEST_SECONDS = 600
KEEP_CLOSED_PICKS = 1000
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class EngineError(Exception):
    pass


def _check_time(value, label: str) -> None:
    if value is not None and not math.isfinite(value):
        raise EngineError(f"{label} must be a finite epoch time")


def _reservations(state: dict, pool: str, now: float) -> int:
    return sum(1 for p in state["picks"].values() if p["pool"] == pool and p.get("outcome") is None and p["lease_until"] > now)


def used_in_force(reading, minutes: int, now: float):
    """Percent used that a stored reading still stands for, or None when it has expired."""
    if not reading:
        return None
    seconds = minutes * 60
    resets = reading.get("resets_at")
    if resets is None:
        return reading["used"] if now < reading["at"] + seconds else None
    if now < resets:
        return reading["used"]
    if now < resets + seconds:
        return 0.0  # the window rolled over at its known reset; without this no host could run to refresh it
    return None


def _window_block(rules: dict, state: dict, name: str, pool: dict, minutes: int, now: float):
    """Return None when this window allows work, else (reason, known restore time or None, fix)."""
    reading = state["readings"].get(name, {}).get(str(minutes))
    fix = f"jumplane reading {name} --window {minutes} --used <percent> --resets-at <epoch>"
    used = used_in_force(reading, minutes, now)
    if used is None:
        if pool.get("allow_unread"):
            return None
        return (f"pool {name} has no valid reading for its {minutes} minute window", None, fix)
    effective = used + _reservations(state, name, now) * rules["reserve_percent"]
    if effective < rules["hold_at_percent"]:
        return None
    resets = reading.get("resets_at")
    restore = resets if resets is not None and resets > now else None
    return (f"pool {name} at {effective:g}% of its {minutes} minute window, holds at {rules['hold_at_percent']:g}%", restore, fix)


def lane_state(rules: dict, state: dict, lane: dict, now: float) -> dict:
    """Eligibility of one lane: open, or blocked with reasons, fixes and a restore time only if all blockers have one."""
    name, pool = lane["pool"], rules["pools"][lane["pool"]]
    blocks = []
    if state["verified"].get(lane["id"]) != lane["model"]:
        blocks.append((f"route {lane['id']} is not verified for {lane['model']}", None, f"jumplane verify {lane['id']}"))
    hold = state["holds"].get(name)
    if hold and (hold["until"] is None or hold["until"] > now):
        blocks.append((f"pool {name} is held: {hold['reason']}", hold["until"], f"jumplane release {name}"))
    if pool["kind"] == "local":
        if lane["model"] not in state["probes"].get(name, {}).get("models", []):
            blocks.append((f"local pool {name} did not list {lane['model']} at its last probe", None, "jumplane init"))
    else:
        for minutes in pool["windows"]:
            block = _window_block(rules, state, name, pool, minutes, now)
            if block:
                blocks.append(block)
        # A host may report windows the rules do not list (Codex can log a 300 minute window). A valid reading of one
        # still holds the pool at the hold line; a missing or expired one is no blocker.
        listed = {str(m) for m in pool["windows"]}
        for key in sorted(state["readings"].get(name, {}), key=lambda k: int(k) if k.isdigit() else 0):
            if key in listed or not key.isdigit() or int(key) <= 0:
                continue
            block = _window_block(rules, state, name, {**pool, "allow_unread": True}, int(key), now)
            if block:
                minutes = int(key)
                blocks.append((block[0], block[1], f"wait for the {name} {minutes} minute window to reset, or add {minutes} to its windows in the rules"))
    if not blocks:
        return {"open": True}
    known = [b[1] for b in blocks]
    return {
        "open": False,
        "reasons": [b[0] for b in blocks],
        "fixes": [b[2] for b in blocks],
        "restore": None if None in known else max(known),
    }


def _prune(state: dict, now: float) -> None:
    state["requests"] = {k: v for k, v in state["requests"].items() if now - v["at"] < REQUEST_SECONDS}
    closed = [k for k, p in state["picks"].items() if p.get("outcome") is not None]
    for key in closed[:-KEEP_CLOSED_PICKS]:
        del state["picks"][key]


def pick(size="medium", risk="medium", complexity="medium", request_id=None, now=None) -> dict:
    now = time.time() if now is None else now
    for value, allowed, label in ((size, rules_mod.SIZES, "size"), (risk, rules_mod.LEVELS, "risk"), (complexity, rules_mod.LEVELS, "complexity")):
        if value not in allowed:
            raise EngineError(f"{label} must be one of {allowed}")
    if request_id is not None and not _REQUEST_ID.match(request_id):
        raise EngineError("request id must be 1 to 64 letters, digits or ._:-")
    rules = rules_mod.load()
    shape = {"size": size, "risk": risk, "complexity": complexity}
    wanted = rules_mod.task_class(rules, size, risk, complexity)
    with store.locked():
        state = store.load()
        _prune(state, now)
        readers.refresh(state, rules)
        if request_id and request_id in state["requests"]:
            earlier = state["requests"][request_id]
            if earlier["shape"] != shape:
                raise EngineError(f"request id {request_id} was already used with a different shape")
            return {**earlier["answer"], "replayed": True}
        skipped = []
        for lane in (l for l in rules["lanes"] if l["class"] == wanted):
            info = lane_state(rules, state, lane, now)
            if info["open"]:
                return _take(rules, state, lane, wanted, shape, skipped, request_id, now)
            skipped.append({"lane": lane["id"], **info})
        answer = _no_lane(wanted, skipped)
        store.save(state)
        store.event(answer["status"], now, wanted=wanted, skipped=[s["lane"] for s in skipped])
        return answer


def _take(rules, state, lane, wanted, shape, skipped, request_id, now) -> dict:
    pick_id = "p-" + secrets.token_hex(8)
    window = rules["pools"][lane["pool"]]["kind"] == "window"
    state["picks"][pick_id] = {
        "lane": lane["id"], "pool": lane["pool"], "at": now, "outcome": None,
        "lease_until": now + rules["lease_seconds"] if window else now,
    }
    reason = f"{shape['size']} size, {shape['risk']} risk, {shape['complexity']} complexity gives class {wanted}"
    if skipped:
        reason += "; passed over " + ", ".join(s["lane"] for s in skipped)
    answer = {
        "status": "picked", "pick_id": pick_id, "lane": lane["id"], "tool": lane["host"], "model": lane["model"],
        "effort": lane["effort"], "class": wanted, "reason": reason, "command": rules_mod.launch_command(lane), "stdin": "closed",  # ollama waits on a piped stdin that stays open
        "skipped": skipped, "replayed": False,
    }
    if request_id:
        state["requests"][request_id] = {"at": now, "shape": shape, "answer": answer}
    store.save(state)
    store.event("picked", now, pick_id=pick_id, lane=lane["id"], wanted=wanted, skipped=[s["lane"] for s in skipped])
    return answer


def _no_lane(wanted: str, skipped: list) -> dict:
    fixes = sorted({fix for s in skipped for fix in s["fixes"]})
    restores = [s["restore"] for s in skipped if s["restore"] is not None]
    if restores:
        return {"status": "wait", "class": wanted, "until": min(restores), "reason": f"no open {wanted} lane until a known reset", "skipped": skipped, "fixes": fixes}
    reason = f"no open {wanted} lane and no known reset" if skipped else f"the rules define no {wanted} lane"
    return {"status": "unavailable", "class": wanted, "reason": reason, "skipped": skipped, "fixes": fixes or [f"add a {wanted} lane to {rules_mod.path()}"]}


def report(pick_id: str, outcome: str, resets_at=None, now=None, tokens=None, receipt=None) -> dict:
    now = time.time() if now is None else now
    _check_time(resets_at, "resets_at")
    if outcome not in OUTCOMES:
        raise EngineError(f"outcome must be one of {OUTCOMES}")
    if tokens is not None and (isinstance(tokens, bool) or not isinstance(tokens, int) or not 0 <= tokens <= 999_999_999):
        raise EngineError("tokens must be a whole number from 0 to 999999999")
    if receipt is not None and (not isinstance(receipt, str) or not receipt or len(receipt) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in receipt)):
        raise EngineError("receipt must be one line of 1 to 500 characters")
    with store.locked():
        state = store.load()
        record = state["picks"].get(pick_id)
        if record is None:
            raise EngineError(f"unknown pick id {pick_id}")
        if record.get("outcome") is not None:
            if record["outcome"] != outcome:
                raise EngineError(f"pick {pick_id} was already reported as {record['outcome']}")
            for key, given in (("tokens", tokens), ("receipt", receipt)):
                if given is not None and record.get(key) != given:
                    raise EngineError(f"pick {pick_id} was already reported with {key} {record.get(key)!r}")
            return {"status": "recorded", "pick_id": pick_id, "outcome": outcome, "replayed": True,
                    "lane": record["lane"], "tokens": record.get("tokens"), "receipt": record.get("receipt")}
        record["outcome"] = outcome
        if tokens is not None:
            record["tokens"] = tokens
        if receipt is not None:
            record["receipt"] = receipt
        if outcome == "limit_hit":
            # No reset known means the hold stays until the owner releases it.
            state["holds"][record["pool"]] = {"until": resets_at, "reason": f"limit hit on {record['lane']}"}
        store.save(state)
        store.event("reported", now, pick_id=pick_id, outcome=outcome, lane=record["lane"], tokens=tokens, receipt=receipt)
    return {"status": "recorded", "pick_id": pick_id, "outcome": outcome, "replayed": False, "lane": record["lane"], "tokens": tokens, "receipt": receipt}


def override(pick_id: str, lane_id: str, reason: str, now=None) -> dict:
    """Record that the caller ran another lane than the one picked, and move the reservation with it."""
    now = time.time() if now is None else now
    if not reason or len(reason) > 200:
        raise EngineError("override reason must be 1 to 200 characters")
    rules = rules_mod.load()
    lane = next((l for l in rules["lanes"] if l["id"] == lane_id), None)
    if lane is None:
        raise EngineError(f"unknown lane {lane_id}")
    with store.locked():
        state = store.load()
        record = state["picks"].get(pick_id)
        if record is None:
            raise EngineError(f"unknown pick id {pick_id}")
        if record.get("outcome") is not None:
            raise EngineError(f"pick {pick_id} is already closed")
        before = record["lane"]
        window = rules["pools"][lane["pool"]]["kind"] == "window"
        record.update(lane=lane_id, pool=lane["pool"], lease_until=now + rules["lease_seconds"] if window else now)
        store.save(state)
        store.event("override", now, pick_id=pick_id, before=before, after=lane_id, reason=reason)
    return {"status": "recorded", "pick_id": pick_id, "lane": lane_id}


def hold(pool: str, until=None, reason="owner hold", now=None) -> dict:
    now = time.time() if now is None else now
    _check_time(until, "until")
    if pool not in rules_mod.load()["pools"]:
        raise EngineError(f"unknown pool {pool}")
    with store.locked():
        state = store.load()
        state["holds"][pool] = {"until": until, "reason": reason}
        store.save(state)
        store.event("hold", now, pool=pool, until=until)
    return {"status": "held", "pool": pool, "until": until}


def release(pool: str, now=None) -> dict:
    now = time.time() if now is None else now
    with store.locked():
        state = store.load()
        removed = state["holds"].pop(pool, None)
        store.save(state)
        store.event("release", now, pool=pool)
    return {"status": "released" if removed else "not_held", "pool": pool}


def record_reading(pool: str, minutes: int, used: float, resets_at=None, source="hand", now=None) -> dict:
    now = time.time() if now is None else now
    _check_time(resets_at, "resets_at")
    rules = rules_mod.load()
    if rules["pools"].get(pool, {}).get("kind") != "window":
        raise EngineError(f"{pool} is not a window pool in the rules")
    if minutes not in rules["pools"][pool]["windows"]:
        raise EngineError(f"pool {pool} has no {minutes} minute window")
    if not 0 <= used <= 100:
        raise EngineError("used must be 0 to 100")
    if resets_at is not None and resets_at <= now:
        raise EngineError("resets_at must be in the future")
    with store.locked():
        state = store.load()
        state["readings"].setdefault(pool, {})[str(minutes)] = {"used": used, "resets_at": resets_at, "at": now, "source": source}
        store.save(state)
        store.event("reading", now, pool=pool, window=minutes, used=used, resets_at=resets_at, source=source)
    return {"status": "recorded", "pool": pool, "window": minutes, "used": used, "resets_at": resets_at}


def as_json(value: dict) -> str:
    return json.dumps(value, indent=1)
