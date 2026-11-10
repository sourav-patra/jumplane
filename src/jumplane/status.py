"""One screen: each pool, used percent, reset, reading age, what is held and what runs next."""
from __future__ import annotations

import datetime
import time

from . import engine, readers, rules as rules_mod, store

WARN_MODEL_DAYS = 30


def _pool_lines(rules: dict, state: dict, name: str, pool: dict, now: float) -> list[str]:
    lines = []
    hold = state["holds"].get(name)
    if hold and (hold["until"] is None or hold["until"] > now):
        until = "until released" if hold["until"] is None else f"for {readers._left(hold['until'] - now)}"
        lines.append(f"{name}  held: {hold['reason']} {until}")
    if pool["kind"] == "local":
        models = state["probes"].get(name, {}).get("models", [])
        lines.append(f"{name}  local, {len(models)} models at last probe")
        return lines
    stored = state["readings"].get(name, {})
    # Windows the host reported but the rules do not list still hold the pool while in force, so show them too.
    extra = sorted(int(k) for k in stored if k.isdigit() and int(k) > 0 and int(k) not in pool["windows"]
                   and engine.used_in_force(stored[k], int(k), now) is not None)
    for minutes in [*pool["windows"], *extra]:
        reading = stored.get(str(minutes))
        if not reading:
            lines.append(f"{name}  {minutes}m no reading")
            continue
        resets = reading["resets_at"]
        left = "no reset known" if resets is None else "reset passed" if resets <= now else f"resets {readers._left(resets - now)}"
        mark = " (not in rules)" if minutes in extra else ""
        lines.append(f"{name}  {minutes}m {reading['used']:g}% {left} read {readers._left(now - reading['at'])} ago ({reading['source']}){mark}")
    return lines


def screen(now=None) -> str:
    now = time.time() if now is None else now
    rules = rules_mod.load()
    with store.locked():
        state = store.load()
        readers.refresh(state, rules)
        store.save(state)
    lines = [text for name, pool in rules["pools"].items() for text in _pool_lines(rules, state, name, pool, now)]
    lines.append("")
    for cls in rules_mod.CLASSES:
        lanes = [lane for lane in rules["lanes"] if lane["class"] == cls]
        infos = [(lane, engine.lane_state(rules, state, lane, now)) for lane in lanes]
        opened = next((lane for lane, info in infos if info["open"]), None)
        if opened:
            lines.append(f"{cls}: next {opened['id']} ({opened['model']})")
            continue
        lines.append(f"{cls}: none open" if lanes else f"{cls}: no lane in the rules")
        fixes = sorted({fix for _, info in infos for fix in info["fixes"]})
        lines.extend(f"  fix: {fix}" for fix in fixes[:3])
        if len(fixes) > 3:
            lines.append(f"  and {len(fixes) - 3} more")
    age = (datetime.date.fromtimestamp(now) - datetime.date.fromisoformat(rules["models_as_of"])).days
    if age > WARN_MODEL_DAYS:
        lines.append(f"\nmodel table is from {rules['models_as_of']}, {age} days old; ranking does not change")
    return "\n".join(lines)
