"""The rules file and the published shape table."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import store

SCHEMA = "jumplane.rules/1"
CLASSES = ("light", "standard", "strong")
SIZES = ("small", "medium", "large")
LEVELS = ("low", "medium", "high")
HOSTS = ("claude", "codex", "ollama")
PROMPT = "<PROMPT>"
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_EFFORT = re.compile(r"^[a-z]{1,16}$")


class RulesError(Exception):
    pass


def shape_class(size: str = "medium", risk: str = "medium", complexity: str = "medium") -> str:
    """Published table: high risk or high complexity is strong; all lowest is light; everything else is standard."""
    if risk == "high" or complexity == "high":
        return "strong"
    if (size, risk, complexity) == ("small", "low", "low"):
        return "light"
    return "standard"


def task_class(rules: dict, size: str, risk: str, complexity: str) -> str:
    """Apply the owner minimum, which holds whatever shape the caller passes."""
    return max(shape_class(size, risk, complexity), rules["minimum_class"], key=CLASSES.index)


def launch_command(lane: dict) -> list[str]:
    model, effort = lane["model"], lane["effort"]
    if lane["host"] == "claude":
        return ["claude", "-p", "--model", model, "--effort", effort, PROMPT]
    if lane["host"] == "codex":
        return ["codex", "exec", "-m", model, "-c", f'model_reasoning_effort="{effort}"', PROMPT]
    return ["ollama", "run", model, PROMPT]


def path() -> Path:
    return store.home() / "rules.json"


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise RulesError(message)


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(rules) -> dict:
    _need(isinstance(rules, dict), "rules must be a JSON object")
    known = {"schema", "models_as_of", "minimum_class", "hold_at_percent", "reserve_percent", "lease_seconds", "pools", "lanes"}
    _need(set(rules) == known, f"rules keys must be exactly {sorted(known)}")
    _need(rules["schema"] == SCHEMA, f"schema must be {SCHEMA}")
    _need(rules["minimum_class"] in CLASSES, f"minimum_class must be one of {CLASSES}")
    _need(_number(rules["hold_at_percent"]) and 0 < rules["hold_at_percent"] <= 100, "hold_at_percent must be above 0 and at most 100")
    _need(_number(rules["reserve_percent"]) and 0 <= rules["reserve_percent"] <= 100, "reserve_percent must be 0 to 100")
    _need(_number(rules["lease_seconds"]) and rules["lease_seconds"] > 0, "lease_seconds must be above 0")
    pools, lanes = rules["pools"], rules["lanes"]
    _need(isinstance(pools, dict) and isinstance(lanes, list), "pools must be an object and lanes a list")
    for name, pool in pools.items():
        _need(bool(_ID.match(name)) and isinstance(pool, dict), f"bad pool {name!r}")
        _need(pool.get("kind") in ("window", "local"), f"pool {name}: kind must be window or local")
        if pool["kind"] == "window":
            windows = pool.get("windows")
            _need(isinstance(windows, list) and bool(windows) and all(isinstance(w, int) and not isinstance(w, bool) and w > 0 for w in windows),
                  f"pool {name}: windows must list minutes")
            _need(isinstance(pool.get("allow_unread", False), bool), f"pool {name}: allow_unread must be true or false")
    seen = set()
    for lane in lanes:
        _need(isinstance(lane, dict) and set(lane) == {"id", "host", "model", "effort", "class", "pool"},
              "each lane needs exactly id, host, model, effort, class, pool")
        _need(isinstance(lane["id"], str) and bool(_ID.match(lane["id"])) and lane["id"] not in seen, f"bad or repeated lane id {lane['id']!r}")
        seen.add(lane["id"])
        _need(lane["host"] in HOSTS, f"lane {lane['id']}: host must be one of {HOSTS}")
        _need(isinstance(lane["model"], str) and bool(_MODEL.match(lane["model"])), f"lane {lane['id']}: bad model")
        _need(isinstance(lane["effort"], str) and bool(_EFFORT.match(lane["effort"])), f"lane {lane['id']}: bad effort")
        _need(lane["class"] in CLASSES, f"lane {lane['id']}: class must be one of {CLASSES}")
        _need(lane["pool"] in pools, f"lane {lane['id']}: unknown pool {lane['pool']!r}")
    return rules


def load() -> dict:
    file = path()
    try:
        return validate(json.loads(file.read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise RulesError(f"no rules at {file}; run: jumplane init") from None
    except (OSError, ValueError, RulesError) as exc:
        raise RulesError(f"{file}: {exc}") from exc
