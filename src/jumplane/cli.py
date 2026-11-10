"""Command line. Answers are JSON on stdout. Exit 0 picked or done, 3 wait, 4 unavailable or refused route, 2 refused input."""
from __future__ import annotations

import argparse

from . import __version__, engine, onboard, readers, rules, status, store

_EXIT = {"wait": 3, "unavailable": 4, "refused": 4}


class _InputError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    """Turn refused arguments into the JSON error answer instead of usage text on stderr."""

    def error(self, message):
        raise _InputError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="jumplane", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("init", help="detect hosts and propose rules; --accept writes them")
    p.add_argument("--accept", action="store_true")
    p.add_argument("--force", action="store_true", help="replace existing rules")
    p.add_argument("--local-model", help="local ollama model for the light lane")
    p = sub.add_parser("verify", help="launch a route once with a trivial prompt, which uses a little of its usage")
    p.add_argument("lane")
    p = sub.add_parser("pick", help="return the lane and launch command for a task shape")
    p.add_argument("--size", choices=rules.SIZES, default="medium")
    p.add_argument("--risk", choices=rules.LEVELS, default="medium")
    p.add_argument("--complexity", choices=rules.LEVELS, default="medium")
    p.add_argument("--request-id")
    p = sub.add_parser("report", help="record the outcome of a pick")
    p.add_argument("pick_id")
    p.add_argument("outcome", choices=engine.OUTCOMES)
    p.add_argument("--resets-at", type=float)
    p.add_argument("--tokens", type=int, help="tokens the unit used, as the host counted them")
    p.add_argument("--receipt", help="path of the unit's receipt file")
    p = sub.add_parser("override", help="record that another lane ran instead")
    p.add_argument("pick_id")
    p.add_argument("lane")
    p.add_argument("--reason", required=True)
    p = sub.add_parser("hold", help="hold a pool")
    p.add_argument("pool")
    p.add_argument("--until", type=float)
    p.add_argument("--reason", default="owner hold")
    p = sub.add_parser("release", help="release a held pool")
    p.add_argument("pool")
    sub.add_parser("status", help="one screen: pools, resets, holds and what runs next")
    sub.add_parser("statusline", help="read a host status line input on stdin, store the reading, print one line")
    p = sub.add_parser("reading", help="record a usage reading by hand")
    p.add_argument("pool")
    p.add_argument("--window", type=int, required=True)
    p.add_argument("--used", type=float, required=True)
    p.add_argument("--resets-at", type=float)
    return parser


def _run(args) -> dict:
    if args.verb == "init":
        return onboard.init(args.accept, args.force, args.local_model)
    if args.verb == "verify":
        return onboard.verify(args.lane)
    if args.verb == "pick":
        return engine.pick(args.size, args.risk, args.complexity, args.request_id)
    if args.verb == "report":
        return engine.report(args.pick_id, args.outcome, args.resets_at, tokens=args.tokens, receipt=args.receipt)
    if args.verb == "override":
        return engine.override(args.pick_id, args.lane, args.reason)
    if args.verb == "hold":
        return engine.hold(args.pool, args.until, args.reason)
    if args.verb == "release":
        return engine.release(args.pool)
    return engine.record_reading(args.pool, args.window, args.used, args.resets_at)


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _InputError as exc:
        print(engine.as_json({"status": "error", "error": str(exc)}))
        return 2
    if args.verb == "statusline":
        print(readers.statusline(readers.read_stdin()))
        return 0
    try:
        if args.verb == "status":
            print(status.screen())
            return 0
        answer = _run(args)
    except (engine.EngineError, rules.RulesError, onboard.SetupError, store.StoreError) as exc:
        print(engine.as_json({"status": "error", "error": str(exc)}))
        return 2
    print(engine.as_json(answer))
    return _EXIT.get(answer["status"], 0)
