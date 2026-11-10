import ast
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from jumplane import engine, onboard, rules, store

NOW = 1_800_000_000.0
SRC = Path(__file__).resolve().parent.parent / "src"


def rules_doc(**changes):
    doc = {
        "schema": rules.SCHEMA, "models_as_of": "2026-11-04", "minimum_class": "light",
        "hold_at_percent": 90, "reserve_percent": 1, "lease_seconds": 3600,
        "pools": {"a": {"kind": "window", "windows": [300], "allow_unread": False},
                  "b": {"kind": "window", "windows": [300, 10080], "allow_unread": False},
                  "local": {"kind": "local"}},
        "lanes": [
            {"id": "a-std", "host": "claude", "model": "m-a", "effort": "medium", "class": "standard", "pool": "a"},
            {"id": "b-std", "host": "codex", "model": "m-b", "effort": "medium", "class": "standard", "pool": "b"},
            {"id": "local-light", "host": "ollama", "model": "m-l", "effort": "default", "class": "light", "pool": "local"},
            {"id": "a-strong", "host": "claude", "model": "m-s", "effort": "high", "class": "strong", "pool": "a"},
        ],
    }
    doc.update(changes)
    return doc


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["JUMPLANE_HOME"] = tmp.name
        self.addCleanup(os.environ.pop, "JUMPLANE_HOME", None)
        os.environ["CODEX_HOME"] = str(Path(tmp.name) / "no-codex")  # never read the real logs
        self.addCleanup(os.environ.pop, "CODEX_HOME", None)
        self.write_rules(rules_doc())
        with store.locked():
            state = store.load()
            state["verified"] = {l["id"]: l["model"] for l in rules_doc()["lanes"]}
            state["probes"]["local"] = {"models": ["m-l"], "at": NOW}
            store.save(state)

    def write_rules(self, doc):
        rules.path().write_text(json.dumps(doc), encoding="utf-8")

    def read_a(self, used=10.0, resets=NOW + 1000):
        engine.record_reading("a", 300, used, resets, now=NOW)

    def read_b(self, used=10.0):
        engine.record_reading("b", 300, used, NOW + 2000, now=NOW)
        engine.record_reading("b", 10080, used, NOW + 9000, now=NOW)


class ShapeTable(unittest.TestCase):
    def test_full_table(self):
        counts = {}
        for s in rules.SIZES:
            for r in rules.LEVELS:
                for c in rules.LEVELS:
                    cls = rules.shape_class(s, r, c)
                    counts[cls] = counts.get(cls, 0) + 1
                    if r == "high" or c == "high":
                        self.assertEqual(cls, "strong")
        self.assertEqual(counts, {"strong": 15, "light": 1, "standard": 11})

    def test_missing_means_medium(self):
        self.assertEqual(rules.shape_class(), "standard")


class Rules(Base):
    def test_owner_minimum_beats_caller_shape(self):
        self.write_rules(rules_doc(minimum_class="standard"))
        self.read_a()
        self.assertEqual(engine.pick("small", "low", "low", now=NOW)["class"], "standard")

    def test_refuses_bad_rules(self):
        for broken in (rules_doc(extra=1), rules_doc(hold_at_percent=0), rules_doc(lanes=[{"id": "x"}]),
                       rules_doc(pools={"a": {"kind": "window", "windows": []}})):
            self.write_rules(broken)
            with self.assertRaises(rules.RulesError):
                rules.load()

    def test_bad_model_cannot_be_an_option(self):
        doc = rules_doc()
        doc["lanes"][0]["model"] = "--dangerous"
        self.write_rules(doc)
        with self.assertRaises(rules.RulesError):
            rules.load()

    def test_no_rules_tells_how(self):
        rules.path().unlink()
        with self.assertRaisesRegex(rules.RulesError, "jumplane init"):
            engine.pick(now=NOW)


class Pick(Base):
    def test_unread_pool_is_unavailable(self):
        answer = engine.pick(now=NOW)
        self.assertEqual(answer["status"], "unavailable")
        self.assertTrue(any("jumplane reading a" in f for f in answer["fixes"]))

    def test_allow_unread_opts_in(self):
        doc = rules_doc()
        doc["pools"]["a"]["allow_unread"] = True
        self.write_rules(doc)
        self.assertEqual(engine.pick(now=NOW)["lane"], "a-std")

    def test_one_known_window_does_not_cover_an_unknown_one(self):
        engine.record_reading("b", 300, 1.0, NOW + 100, now=NOW)
        self.assertEqual(engine.pick(now=NOW)["status"], "unavailable")

    def test_ties_follow_owner_order(self):
        self.read_a()
        self.read_b()
        self.assertEqual(engine.pick(now=NOW)["lane"], "a-std")

    def test_jumps_to_next_lane_near_limit(self):
        self.read_a(used=95.0)
        self.read_b()
        answer = engine.pick(now=NOW)
        self.assertEqual(answer["lane"], "b-std")
        self.assertEqual(answer["skipped"][0]["lane"], "a-std")
        self.assertIn("codex", answer["command"])
        self.assertEqual(answer["stdin"], "closed")

    def test_wait_only_when_known_reset_restores(self):
        self.read_a(used=95.0, resets=NOW + 500)
        answer = engine.pick(now=NOW)  # b is unread, so only a can come back
        self.assertEqual((answer["status"], answer["until"]), ("wait", NOW + 500))

    def test_over_limit_without_reset_is_unavailable(self):
        self.read_a(used=95.0, resets=None)
        self.assertEqual(engine.pick(now=NOW)["status"], "unavailable")

    def test_reading_rolls_over_at_reset_then_expires(self):
        self.read_a(used=95.0, resets=NOW + 500)
        self.assertEqual(engine.pick(now=NOW + 501)["lane"], "a-std")
        self.assertEqual(engine.pick(now=NOW + 501 + 300 * 60)["status"], "unavailable")

    def test_reading_without_reset_lasts_one_window(self):
        self.read_a(resets=None)
        self.assertEqual(engine.pick(now=NOW + 300 * 60 - 1)["lane"], "a-std")
        self.assertEqual(engine.pick(now=NOW + 300 * 60)["status"], "unavailable")

    def test_hold_beats_reading_and_blocks_past_it(self):
        self.read_a()
        engine.hold("a", NOW + 50, now=NOW)
        answer = engine.pick(now=NOW)
        self.assertEqual((answer["status"], answer["until"]), ("wait", NOW + 50))
        self.assertEqual(engine.pick(now=NOW + 51)["lane"], "a-std")

    def test_hold_with_no_end_needs_release(self):
        self.read_a()
        engine.hold("a", now=NOW)
        answer = engine.pick(now=NOW)
        self.assertEqual(answer["status"], "unavailable")
        self.assertIn("jumplane release a", answer["fixes"])
        engine.release("a", now=NOW)
        self.assertEqual(engine.pick(now=NOW)["lane"], "a-std")

    def test_restore_waits_for_the_latest_blocker(self):
        self.read_a(used=95.0, resets=NOW + 500)
        engine.hold("a", NOW + 900, now=NOW)
        self.assertEqual(engine.pick(now=NOW)["until"], NOW + 900)

    def test_unverified_route_refused_not_substituted(self):
        self.read_a()
        with store.locked():
            state = store.load()
            state["verified"]["a-std"] = "older-model"
            store.save(state)
        answer = engine.pick(now=NOW)
        self.assertEqual(answer["status"], "unavailable")
        self.assertIn("jumplane verify a-std", answer["fixes"])

    def test_no_lane_in_class_does_not_borrow_a_class(self):
        doc = rules_doc()
        doc["lanes"] = [l for l in doc["lanes"] if l["class"] != "standard"]
        self.write_rules(doc)
        self.read_a()
        answer = engine.pick(now=NOW)
        self.assertEqual(answer["status"], "unavailable")
        self.assertIn("standard", answer["fixes"][0])

    def test_local_pool_follows_last_probe(self):
        self.assertEqual(engine.pick("small", "low", "low", now=NOW)["lane"], "local-light")
        with store.locked():
            state = store.load()
            state["probes"]["local"]["models"] = ["other"]
            store.save(state)
        answer = engine.pick("small", "low", "low", now=NOW)
        self.assertEqual(answer["status"], "unavailable")
        self.assertIn("jumplane init", answer["fixes"])

    def test_refuses_bad_shape(self):
        with self.assertRaises(engine.EngineError):
            engine.pick(size="huge", now=NOW)


class Retries(Base):
    def test_same_request_answers_once_for_600_seconds(self):
        self.read_a(used=85.0)
        self.read_b()
        first = engine.pick(request_id="r1", now=NOW)
        again = engine.pick(request_id="r1", now=NOW + 599)
        self.assertEqual(again["pick_id"], first["pick_id"])
        self.assertTrue(again["replayed"])
        self.assertEqual(len(store.load()["picks"]), 1)
        self.assertNotEqual(engine.pick(request_id="r1", now=NOW + 600)["pick_id"], first["pick_id"])

    def test_request_id_with_other_shape_refused(self):
        self.read_a()
        engine.pick(request_id="r1", now=NOW)
        with self.assertRaises(engine.EngineError):
            engine.pick(risk="high", request_id="r1", now=NOW)

    def test_reservations_count_until_lease_ends(self):
        self.read_a(used=88.0)
        self.assertEqual(engine.pick(now=NOW)["lane"], "a-std")
        self.assertEqual(engine.pick(now=NOW)["lane"], "a-std")
        self.assertEqual(engine.pick(now=NOW)["status"], "wait")
        self.assertEqual(engine.pick(now=NOW + 3601)["lane"], "a-std")

    def test_report_frees_the_reservation(self):
        self.read_a(used=89.0)
        first = engine.pick(now=NOW)
        self.assertEqual(engine.pick(now=NOW)["status"], "wait")
        engine.report(first["pick_id"], "done", now=NOW)
        self.assertEqual(engine.pick(now=NOW)["lane"], "a-std")

    def test_report_keeps_tokens_and_receipt(self):
        self.read_a(used=10.0)
        first = engine.pick(now=NOW)
        answer = engine.report(first["pick_id"], "done", now=NOW, tokens=1234, receipt="Context/r.md")
        self.assertEqual((answer["tokens"], answer["receipt"], answer["lane"]), (1234, "Context/r.md", "a-std"))
        record = store.load()["picks"][first["pick_id"]]
        self.assertEqual((record["tokens"], record["receipt"]), (1234, "Context/r.md"))

    def test_report_refuses_bad_tokens_and_receipt(self):
        self.read_a(used=10.0)
        first = engine.pick(now=NOW)
        for bad in (-1, 10**9, True, "5"):
            with self.assertRaises(engine.EngineError):
                engine.report(first["pick_id"], "done", now=NOW, tokens=bad)
        for bad in ("", "a\nb", "a\rb", "a\x00b", "x" * 501):
            with self.assertRaises(engine.EngineError):
                engine.report(first["pick_id"], "done", now=NOW, receipt=bad)
        self.assertIsNone(store.load()["picks"][first["pick_id"]]["outcome"])

    def test_report_token_bounds_events_and_override(self):
        self.read_a(used=10.0)
        for tokens in (0, 999_999_999):
            first = engine.pick(now=NOW)
            self.assertEqual(engine.report(first["pick_id"], "done", now=NOW, tokens=tokens)["tokens"], tokens)
        moved = engine.pick(now=NOW)
        engine.override(moved["pick_id"], "b-std", "owner ran codex", now=NOW)
        answer = engine.report(moved["pick_id"], "limit_hit", resets_at=NOW + 600, now=NOW, tokens=7, receipt="r.md")
        self.assertEqual(answer["lane"], "b-std")
        self.assertIn("b", store.load()["holds"])
        last = json.loads((store.home() / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((last["lane"], last["tokens"], last["receipt"], last["outcome"]), ("b-std", 7, "r.md", "limit_hit"))

    def test_replayed_report_returns_stored_fields_and_refuses_conflicts(self):
        self.read_a(used=10.0)
        first = engine.pick(now=NOW)
        engine.report(first["pick_id"], "limit_hit", resets_at=NOW + 600, now=NOW, tokens=1234, receipt="r.md")
        hold = dict(store.load()["holds"]["a"])
        for kwargs in ({}, {"tokens": 1234, "receipt": "r.md"}):
            again = engine.report(first["pick_id"], "limit_hit", now=NOW, **kwargs)
            self.assertEqual((again["replayed"], again["lane"], again["tokens"], again["receipt"]), (True, "a-std", 1234, "r.md"))
        for kwargs in ({"tokens": 5678}, {"receipt": "other.md"}):
            with self.assertRaises(engine.EngineError):
                engine.report(first["pick_id"], "limit_hit", now=NOW, **kwargs)
        self.assertEqual(store.load()["holds"]["a"], hold)
        events = (store.home() / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum('"reported"' in line for line in events), 1)

    def test_local_pool_takes_no_reservation(self):
        answer = engine.pick("small", "low", "low", now=NOW)
        self.assertEqual(store.load()["picks"][answer["pick_id"]]["lease_until"], NOW)

    def test_two_processes_race_for_last_headroom(self):
        self.read_a(used=88.5)
        code = f"from jumplane import engine;print(engine.pick(now={NOW})['status'])"
        env = {**os.environ, "PYTHONPATH": str(SRC)}
        runs = [subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True) for _ in range(6)]
        results = sorted(r.communicate()[0].strip() for r in runs)
        self.assertEqual(results.count("picked"), 2, results)  # 88.5, then 89.5; 90.5 holds
        self.assertEqual(len(store.load()["picks"]), 2)


class Report(Base):
    def setUp(self):
        super().setUp()
        self.read_a()
        self.pick_id = engine.pick(now=NOW)["pick_id"]

    def test_outcomes_are_closed(self):
        with self.assertRaises(engine.EngineError):
            engine.report(self.pick_id, "great", now=NOW)

    def test_repeat_is_safe_and_conflict_refused(self):
        engine.report(self.pick_id, "done", now=NOW)
        self.assertTrue(engine.report(self.pick_id, "done", now=NOW)["replayed"])
        with self.assertRaises(engine.EngineError):
            engine.report(self.pick_id, "failed", now=NOW)

    def test_limit_hit_holds_pool_until_reset(self):
        engine.report(self.pick_id, "limit_hit", resets_at=NOW + 70, now=NOW)
        self.assertEqual(engine.pick(now=NOW)["until"], NOW + 70)

    def test_limit_hit_without_reset_holds_until_release(self):
        engine.report(self.pick_id, "limit_hit", now=NOW)
        self.assertEqual(engine.pick(now=NOW + 10 ** 6)["status"], "unavailable")

    def test_unknown_pick(self):
        with self.assertRaises(engine.EngineError):
            engine.report("p-none", "done", now=NOW)

    def test_override_moves_reservation_and_logs(self):
        engine.override(self.pick_id, "b-std", "owner ran it there", now=NOW)
        record = store.load()["picks"][self.pick_id]
        self.assertEqual((record["lane"], record["pool"]), ("b-std", "b"))
        log = (store.home() / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"before": "a-std"', log)
        engine.report(self.pick_id, "done", now=NOW)
        with self.assertRaises(engine.EngineError):
            engine.override(self.pick_id, "a-std", "late", now=NOW)

    def test_override_refuses_unknown_lane_and_long_reason(self):
        with self.assertRaises(engine.EngineError):
            engine.override(self.pick_id, "nope", "r", now=NOW)
        with self.assertRaises(engine.EngineError):
            engine.override(self.pick_id, "b-std", "r" * 201, now=NOW)


class Readings(Base):
    def test_bounds(self):
        for args in (("a", 300, 101.0), ("a", 300, -1.0), ("a", 300, float("nan")), ("a", 60, 1.0), ("nope", 300, 1.0), ("local", 300, 1.0)):
            with self.assertRaises(engine.EngineError):
                engine.record_reading(*args, now=NOW)
        for resets in (NOW - 1, float("nan"), float("inf")):
            with self.assertRaises(engine.EngineError):
                engine.record_reading("a", 300, 1.0, resets, now=NOW)


class Store(Base):
    def test_lock_is_reentrant_in_a_thread(self):
        with store.locked():
            with store.locked():
                store.save(store.load())

    def test_lock_wait_is_bounded(self):
        code = ("import time;from jumplane import store;\n"
                "with store.locked():\n    print('in',flush=True);time.sleep(4)")
        child = subprocess.Popen([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": str(SRC)}, stdout=subprocess.PIPE, text=True)
        self.addCleanup(child.communicate)
        child.stdout.readline()
        original, store.LOCK_WAIT_SECONDS = store.LOCK_WAIT_SECONDS, 0.1
        self.addCleanup(setattr, store, "LOCK_WAIT_SECONDS", original)
        with self.assertRaises(store.StoreError):
            with store.locked():
                pass

    def test_dead_process_leaves_no_lock(self):
        code = "import os;from jumplane import store;\nwith store.locked():\n    os._exit(9)"
        subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": str(SRC)})
        with store.locked():
            pass

    def test_corrupt_state_is_reported(self):
        (store.home() / "state.json").write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(store.StoreError, "state.json"):
            store.load()

    def test_threads_do_not_lose_writes(self):
        self.read_a()
        self.write_rules(rules_doc(reserve_percent=0))
        threads = [threading.Thread(target=engine.pick, kwargs={"now": NOW}) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(store.load()["picks"]), 8)


class Setup(Base):
    def setUp(self):
        super().setUp()
        rules.path().unlink()
        self.addCleanup(setattr, onboard.probe, "ollama_models", onboard.probe.ollama_models)
        self.addCleanup(setattr, onboard.probe, "host_present", onboard.probe.host_present)
        self.addCleanup(setattr, onboard.probe, "run_verify", onboard.probe.run_verify)
        onboard.probe.ollama_models = lambda: ["small:1"]
        onboard.probe.host_present = lambda host: True

    def test_propose_writes_nothing_and_refuses_unverified(self):
        answer = onboard.init(now=NOW)
        self.assertEqual(answer["status"], "proposed")
        self.assertFalse(rules.path().exists())
        self.assertEqual(len(answer["refused"]), 6)
        self.assertIn("jumplane verify claude-light", [r["command"] for r in answer["refused"]])

    def test_accept_then_local_pick_works_with_no_hosted_lane(self):
        onboard.init(accept=True, now=NOW)
        answer = engine.pick("small", "low", "low", now=NOW)
        self.assertEqual((answer["lane"], answer["command"][:3]), ("ollama-light", ["ollama", "run", "small:1"]))
        self.assertEqual(engine.pick(now=NOW)["status"], "unavailable")

    def test_reprobe_closes_a_removed_local_model(self):
        onboard.init(accept=True, now=NOW)
        onboard.probe.ollama_models = lambda: ["other:1"]
        onboard.init(now=NOW)
        self.assertEqual(engine.pick("small", "low", "low", now=NOW)["status"], "unavailable")

    def test_accept_never_overwrites_without_force(self):
        onboard.init(accept=True, now=NOW)
        with self.assertRaises(onboard.SetupError):
            onboard.init(accept=True, now=NOW)
        onboard.init(accept=True, force=True, now=NOW)

    def test_absent_hosts_and_server(self):
        onboard.probe.ollama_models = lambda: None
        onboard.probe.host_present = lambda host: False
        answer = onboard.init(accept=True, now=NOW)
        self.assertEqual(answer["rules"]["lanes"], [])
        self.assertEqual(engine.pick(now=NOW)["status"], "unavailable")

    def test_named_local_model_must_exist(self):
        with self.assertRaises(onboard.SetupError):
            onboard.init(local_model="absent:1", now=NOW)

    def test_verify_runs_codex_outside_a_trusted_folder_read_only(self):
        lane = {"host": "codex", "model": "m", "effort": "low"}
        self.assertEqual(onboard.verify_command(lane)[:6], ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-m"])
        self.assertNotIn("--skip-git-repo-check", rules.launch_command(lane))

    def test_verify_records_and_failure_removes(self):
        onboard.init(accept=True, now=NOW)
        onboard.probe.run_verify = lambda command: (True, "launched")
        self.assertEqual(onboard.verify("claude-light", now=NOW)["status"], "verified")
        self.assertEqual(store.load()["verified"]["claude-light"], "claude-haiku-5-5")
        onboard.probe.run_verify = lambda command: (False, "exit 1")
        self.assertEqual(onboard.verify("claude-light", now=NOW)["status"], "refused")
        self.assertNotIn("claude-light", store.load()["verified"])


class Probe(unittest.TestCase):
    def test_dead_server_is_none(self):
        self.assertIsNone(onboard.probe.ollama_models("http://127.0.0.1:9/none", timeout=0.2))

    def test_probe_refuses_addresses_off_loopback(self):
        for url in ("http://example.com/api/tags", "http://10.0.0.1:11434/api/tags", "https://127.0.0.1:11434/api/tags", "file:///etc/hosts"):
            self.assertIsNone(onboard.probe.ollama_models(url, timeout=0.2), url)

    def test_probe_refuses_a_redirect_and_ignores_proxy_settings(self):
        import http.server
        hits = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                if self.path == "/api/tags":
                    self.send_response(302)
                    self.send_header("Location", "/moved")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = json.dumps({"models": [{"name": "m:1"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        keys = ("HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")
        saved = {k: os.environ.pop(k, None) for k in keys}
        os.environ["HTTP_PROXY"] = os.environ["http_proxy"] = "http://192.0.2.1:9"  # an unroutable proxy: using it would fail
        try:
            self.assertEqual(onboard.probe.ollama_models(base + "/moved", timeout=2), ["m:1"])
            self.assertIsNone(onboard.probe.ollama_models(base + "/api/tags", timeout=2))
        finally:
            for key, value in saved.items():
                os.environ.pop(key, None)
                if value is not None:
                    os.environ[key] = value
        self.assertEqual(hits, ["/moved", "/api/tags"])
        self.assertFalse([h for h in onboard.probe._OPENER.handlers if isinstance(h, urllib.request.ProxyHandler) and h.proxies])

    def test_prompt_placeholder_replaced(self):
        ok, _ = onboard.probe.run_verify([sys.executable, "-c", "import sys;sys.exit(0 if sys.argv[1].startswith('Reply') else 1)", "<PROMPT>"])
        self.assertTrue(ok)

    def test_failed_launch(self):
        self.assertFalse(onboard.probe.run_verify([sys.executable, "-c", "raise SystemExit(5)"])[0])
        self.assertFalse(onboard.probe.run_verify(["no-such-host-binary"])[0])


def _imports(file):
    for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            yield node.module.split(".")[0]


class Governance(unittest.TestCase):
    def test_only_probe_may_touch_the_network_or_processes(self):
        banned = {"socket", "urllib", "http", "subprocess", "ssl", "ftplib", "smtplib", "asyncio"}
        for file in (SRC / "jumplane").glob("*.py"):
            if file.name != "probe.py":
                self.assertFalse(banned & set(_imports(file)), file.name)

    def test_standard_library_only(self):
        for file in (SRC / "jumplane").glob("*.py"):
            for name in _imports(file):
                self.assertIn(name, sys.stdlib_module_names, file.name)


class CommandLine(Base):
    def run_cli(self, *args):
        done = subprocess.run([sys.executable, "-m", "jumplane", *args], env={**os.environ, "PYTHONPATH": str(SRC)}, capture_output=True, text=True)
        return done.returncode, json.loads(done.stdout)

    def test_exit_codes_and_full_loop(self):
        code, answer = self.run_cli("pick")
        self.assertEqual((code, answer["status"]), (4, "unavailable"))
        code, _ = self.run_cli("reading", "a", "--window", "300", "--used", "95", "--resets-at", "99999999999")
        self.assertEqual(code, 0)
        code, answer = self.run_cli("pick")
        self.assertEqual((code, answer["status"]), (3, "wait"))
        self.run_cli("reading", "a", "--window", "300", "--used", "5", "--resets-at", "99999999999")
        code, answer = self.run_cli("pick", "--request-id", "x1")
        self.assertEqual((code, answer["lane"]), (0, "a-std"))
        code, done = self.run_cli("report", answer["pick_id"], "done")
        self.assertEqual((code, done["outcome"]), (0, "done"))

    def test_report_flags_through_the_command_line(self):
        self.run_cli("reading", "a", "--window", "300", "--used", "5", "--resets-at", "99999999999")
        _, answer = self.run_cli("pick")
        for bad in ("abc", "1.5", "-1"):
            code, refused = self.run_cli("report", answer["pick_id"], "done", "--tokens", bad)
            self.assertEqual((code, refused["status"]), (2, "error"))
        code, done = self.run_cli("report", answer["pick_id"], "done", "--tokens", "42", "--receipt", "r.md")
        self.assertEqual((code, done["tokens"], done["receipt"]), (0, 42, "r.md"))
        code, again = self.run_cli("report", answer["pick_id"], "done")
        self.assertEqual((code, again["replayed"], again["tokens"]), (0, True, 42))

    def test_error_is_json_with_exit_2(self):
        code, answer = self.run_cli("report", "p-none", "done")
        self.assertEqual((code, answer["status"]), (2, "error"))


if __name__ == "__main__":
    unittest.main()
