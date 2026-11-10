import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jumplane import engine, readers, rules, status, store
from tests.test_engine import NOW, SRC, Base


def rate_event(used=64.0, window=10080, resets=NOW + 5000, stamp="2027-01-15T08:00:00.000Z"):
    return json.dumps({"timestamp": stamp, "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
        "primary": {"used_percent": used, "window_minutes": window, "resets_at": resets}, "secondary": None}}})


def host_input(five=12.0, seven=40.0):
    return json.dumps({"cwd": "x", "rate_limits": {
        "five_hour": {"used_percentage": five, "resets_at": NOW + 3600},
        "seven_day": {"used_percentage": seven, "resets_at": NOW + 90000}}}).encode()


class Statusline(Base):
    def test_stores_both_windows_and_prints_one_line(self):
        line = readers.statusline(host_input(), now=NOW)
        self.assertEqual(line, "5h 12% resets 1h00m | 7d 40% resets 1d1h")
        held = store.load()["readings"]["claude"]
        self.assertEqual((held["300"]["used"], held["10080"]["used"], held["300"]["source"]), (12.0, 40.0, "statusline"))

    def test_bad_input_never_raises_or_stores(self):
        for raw in (b"", b"{", b"[]", b'{"rate_limits":null}', b'{"rate_limits":{"five_hour":{"used_percentage":"x","resets_at":1}}}',
                    b'{"rate_limits":{"five_hour":{"used_percentage":500,"resets_at":1}}}', b"\xff\xfe"):
            self.assertIn("no limit data", readers.statusline(raw, now=NOW))
        self.assertEqual(store.load()["readings"], {})

    def test_broken_state_still_prints_the_line(self):
        (store.home() / "state.json").write_text("{", encoding="utf-8")
        self.assertIn("5h 12%", readers.statusline(host_input(), now=NOW))

    def test_command_exits_zero_on_garbage(self):
        done = subprocess.run([sys.executable, "-m", "jumplane", "statusline"], input=b"garbage", capture_output=True, env={**os.environ, "PYTHONPATH": str(SRC)})
        self.assertEqual(done.returncode, 0)
        self.assertIn(b"no limit data", done.stdout)


class CodexLog(Base):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "sessions"

    def log(self, day, name, *lines):
        folder = self.root / day
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"rollout-{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_last_event_in_newest_day_wins(self):
        self.log("2027/01/14", "old", rate_event(used=1.0))
        self.log("2027/01/15", "new", rate_event(used=2.0), rate_event(used=3.0), '{"type":"other"}')
        self.assertEqual(readers.read_codex(self.root)[0][:3], (10080, 3.0, NOW + 5000))

    def test_surprises_mean_no_reading(self):
        self.assertEqual(readers.read_codex(self.root), [])
        for bad in ('{"rate_limits": broken', '{"payload":{"rate_limits":{}},"timestamp":"nope"}', rate_event(used=500)):
            self.log("2027/01/15", "x", bad)
            self.assertEqual(readers.read_codex(self.root), [])

    def test_pick_jumps_when_the_log_crosses_the_threshold(self):
        os.environ["CODEX_HOME"] = str(self.root.parent)
        self.log("2027/01/15", "x", rate_event(used=20.0))
        doc = json.loads(rules.path().read_text(encoding="utf-8"))
        doc["pools"]["b"]["windows"] = [10080]
        doc["lanes"].reverse()
        rules.path().write_text(json.dumps(doc), encoding="utf-8")
        engine.record_reading("a", 300, 10.0, NOW + 1000, now=NOW)
        self.assertEqual(engine.pick(now=NOW)["lane"], "b-std")
        self.log("2027/01/15", "x", rate_event(used=95.0, stamp="2027-01-15T09:00:00.000Z"))
        answer = engine.pick(now=NOW)
        self.assertEqual(answer["lane"], "a-std")
        self.assertEqual(answer["skipped"][0]["lane"], "b-std")

    def weekly_only_rules(self):
        os.environ["CODEX_HOME"] = str(self.root.parent)
        doc = json.loads(rules.path().read_text(encoding="utf-8"))
        doc["pools"]["b"]["windows"] = [10080]
        doc["lanes"].reverse()  # b-std first in class standard
        rules.path().write_text(json.dumps(doc), encoding="utf-8")
        engine.record_reading("a", 300, 10.0, NOW + 1000, now=NOW)

    def test_exhausted_short_window_holds_a_pool_whose_rules_list_only_the_weekly_one(self):
        self.weekly_only_rules()
        event = json.dumps({"timestamp": "2027-01-15T08:00:00.000Z", "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 100.0, "window_minutes": 300, "resets_at": NOW + 600},
            "secondary": {"used_percent": 5.0, "window_minutes": 10080, "resets_at": NOW + 90000}}}})
        self.log("2027/01/15", "x", event)
        answer = engine.pick(now=NOW)
        self.assertEqual(answer["lane"], "a-std")
        skipped = answer["skipped"][0]
        self.assertEqual(skipped["lane"], "b-std")
        self.assertEqual(skipped["reasons"], ["pool b at 100% of its 300 minute window, holds at 90%"])
        self.assertEqual(skipped["restore"], NOW + 600)

    def test_weekly_reading_alone_still_picks(self):
        self.weekly_only_rules()
        self.log("2027/01/15", "x", rate_event(used=5.0))
        self.assertEqual(engine.pick(now=NOW)["lane"], "b-std")

    def test_expired_short_window_reading_does_not_block(self):
        self.weekly_only_rules()
        state = store.load()
        readers.keep(state, "b", 300, 100.0, NOW - 20000, NOW - 30000, "codex-log")  # its reset plus one window has passed
        store.save(state)
        self.log("2027/01/15", "x", rate_event(used=5.0))
        self.assertEqual(engine.pick(now=NOW)["lane"], "b-std")

    def test_older_event_does_not_replace_a_newer_reading(self):
        state = store.load()
        readers.keep(state, "b", 10080, 50.0, NOW + 1, 200.0, "x")
        readers.keep(state, "b", 10080, 10.0, NOW + 1, 100.0, "x")
        self.assertEqual(state["readings"]["b"]["10080"]["used"], 50.0)


class Status(Base):
    def setUp(self):
        super().setUp()
        os.environ["CODEX_HOME"] = str(store.home() / "no-codex")
        self.addCleanup(os.environ.pop, "CODEX_HOME", None)

    def test_screen_shows_lane_pool_hold_and_next(self):
        engine.record_reading("a", 300, 95.0, NOW + 3600, now=NOW)
        engine.hold("b", now=NOW)
        screen = status.screen(now=NOW + 60)
        for text in ("a  300m 95%", "resets 0h59m", "read 0h01m ago", "b  held: owner hold", "light: next local-light", "standard: none open", "b  300m no reading"):
            self.assertIn(text, screen)
        self.assertEqual(len(store.load()["picks"]), 0)

    def test_screen_shows_a_window_the_rules_do_not_list(self):
        state = store.load()
        readers.keep(state, "a", 10080, 100.0, NOW + 7200, NOW, "codex-log")  # pool a lists only 300
        readers.keep(state, "a", 60, 50.0, NOW - 20000, NOW - 30000, "codex-log")  # expired: not shown
        store.save(state)
        engine.record_reading("a", 300, 10.0, NOW + 1000, now=NOW)
        screen = status.screen(now=NOW + 60)
        self.assertIn("a  10080m 100% resets 1h59m read 0h01m ago (codex-log) (not in rules)", screen)
        self.assertNotIn("a  60m", screen)
        self.assertIn("a  300m 10%", screen)
        self.assertNotIn("(not in rules)", screen.split("a  10080m")[0])

    def test_old_model_table_warns_and_does_not_change_ranking(self):
        doc = json.loads(rules.path().read_text(encoding="utf-8"))
        doc["models_as_of"] = "2020-01-01"
        rules.path().write_text(json.dumps(doc), encoding="utf-8")
        self.assertIn("model table is from 2020-01-01", status.screen(now=NOW))
        self.assertEqual(engine.pick("small", "low", "low", now=NOW)["lane"], "local-light")

    def test_no_rules_tells_how(self):
        rules.path().unlink()
        with self.assertRaisesRegex(rules.RulesError, "jumplane init"):
            status.screen(now=NOW)
