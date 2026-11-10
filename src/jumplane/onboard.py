"""`init` and `verify`: propose rules from what this machine has, and verify routes."""
from __future__ import annotations

import json
import time

from . import probe, routes, rules as rules_mod, store


class SetupError(Exception):
    pass


def propose(local_model: str | None = None) -> tuple[dict, dict]:
    """Return proposed rules and the probe results. Local lanes come first because they cost nothing."""
    models = probe.ollama_models()
    chosen = None
    if models:
        if local_model and local_model not in models:
            raise SetupError(f"{local_model} is not served by local ollama; it serves: {', '.join(models)}")
        chosen = local_model or models[0]
    lanes, pools = [], {}
    if chosen:
        pools["ollama"] = {"kind": "local"}
        lanes.append({"id": "ollama-light", "host": "ollama", "model": chosen, "effort": "default", "class": "light", "pool": "ollama"})
    hosts = {}
    for lane_id, host, model, effort, cls in routes.ROUTES:
        hosts.setdefault(host, probe.host_present(host))
        if hosts[host]:
            pools.setdefault(host, {"kind": "window", "windows": routes.WINDOWS[host], "allow_unread": False})
            lanes.append({"id": lane_id, "host": host, "model": model, "effort": effort, "class": cls, "pool": host})
    proposal = {
        "schema": rules_mod.SCHEMA, "models_as_of": routes.MODELS_AS_OF, "minimum_class": "light",
        "hold_at_percent": 90, "reserve_percent": 1, "lease_seconds": 3600, "pools": pools, "lanes": lanes,
    }
    return rules_mod.validate(proposal), {"hosts": hosts, "ollama_models": models}


def init(accept=False, force=False, local_model=None, now=None) -> dict:
    now = time.time() if now is None else now
    proposal, found = propose(local_model)
    target = rules_mod.path()
    refused = [
        {"lane": lane["id"], "reason": "route not verified", "command": f"jumplane verify {lane['id']}"}
        for lane in proposal["lanes"] if lane["host"] != "ollama"
    ]
    answer = {"status": "proposed", "rules_path": str(target), "rules": proposal, "found": found, "refused": refused,
              "claude_settings_line": {"statusLine": {"type": "command", "command": "jumplane statusline"}}}
    with store.locked():
        state = store.load()
        # shortcut: the probe covers only the pool named ollama, which is what init writes; extend it if hand-written rules need other local pools.
        state["probes"]["ollama"] = {"models": found["ollama_models"] or [], "at": now}
        if accept:
            if target.exists() and not force:
                raise SetupError(f"{target} exists; pass --force to replace it")
            store.write_atomic(target, json.dumps(proposal, indent=1) + "\n")
            for lane in proposal["lanes"]:
                if lane["host"] == "ollama":  # the loopback listing just read shows this model is served
                    state["verified"][lane["id"]] = lane["model"]
            store.event("rules_accepted", now, lanes=[l["id"] for l in proposal["lanes"]])
            answer["status"] = "accepted"
        store.save(state)
    return answer


def verify_command(lane: dict) -> list[str]:
    """The launch command, run once from wherever verify is called. Codex refuses a folder it does not trust,
    so the trivial prompt skips that check and runs read-only; commands that pick returns keep the check."""
    command = rules_mod.launch_command(lane)
    if lane["host"] == "codex":
        command[2:2] = ["--skip-git-repo-check", "-s", "read-only"]
    return command


def verify(lane_id: str, now=None) -> dict:
    now = time.time() if now is None else now
    lane = next((l for l in rules_mod.load()["lanes"] if l["id"] == lane_id), None)
    if lane is None:
        raise SetupError(f"unknown lane {lane_id}")
    ok, detail = probe.run_verify(verify_command(lane))  # outside the lock: a launch can take minutes
    with store.locked():
        state = store.load()
        if ok:
            state["verified"][lane_id] = lane["model"]
        else:
            state["verified"].pop(lane_id, None)
        store.save(state)
        store.event("verify", now, lane=lane_id, ok=ok)
    return {"status": "verified" if ok else "refused", "lane": lane_id, "model": lane["model"], "detail": detail}
