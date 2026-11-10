# Guide: pick, launch, report

This page takes a person at a terminal, or a coding agent that can run shell commands, through one full loop: `init`, `verify`, `pick`, launch the returned command, `report`.

Every command in sections 1 to 9 was run as written on Windows 11 in Git Bash on 10 Nov 2026; the outputs shown are from that run, shortened where marked. The hosted-only variant in [Without Ollama](#without-ollama) was not run for this page, so as not to spend plan usage.

jumplane answers in JSON on stdout, except `status`, which prints a screen of text. Callers read stdout and the exit code; [the table at the end](#exit-codes) lists the codes.

## Before you start

Sections 1 to 9 use a local lane, so they need [Ollama](https://ollama.com) running on this machine with at least one model pulled. The examples use `qwen3.5:9b`; put any tag from `ollama list` in its place. With only Claude Code or Codex installed, follow sections 1 and 2 (leave out `--local-model`), then [Without Ollama](#without-ollama).

## 1. Use a scratch state folder

jumplane keeps its rules, state and event log in `~/.jumplane`. The `JUMPLANE_HOME` variable moves them, so you can try the loop without touching real state.

```bash
mkdir -p "$HOME/jumplane-try" && cd "$HOME/jumplane-try"
export JUMPLANE_HOME="$HOME/jumplane-try/state"
```

## 2. Propose and accept rules

`init` looks for `claude` and `codex` on the PATH and asks a local Ollama server at `127.0.0.1:11434` which models it serves. It prints proposed rules and does not write the rules file. It does record the Ollama listing in `state.json`, and that listing decides which local lanes are open.

```bash
jumplane init
```

The answer has `"status": "proposed"`, the rules, what it found, a `refused` list of hosted lanes that still need `verify`, and the `claude_settings_line` to add to `~/.claude/settings.json` so Claude Code feeds its usage readings to jumplane.

Read the rules, then accept them. `--local-model` names the Ollama model for the light lane; without it, `init` takes the first model Ollama lists.

```bash
jumplane init --accept --local-model qwen3.5:9b
```

Check: the answer says `"status": "accepted"` and `rules_path` points into the scratch folder. A model Ollama does not serve is refused with exit 2 and the list of models it does serve.

## 3. Verify a route

A lane is refused until `verify` has launched it once. `verify` sends the prompt "Reply with the single word OK." with stdin closed and waits up to 180 seconds.

```bash
jumplane verify ollama-light
```

Check: `"status": "verified"`. A failed launch answers `"status": "refused"` with the cause in `detail`, and exit 4. `init --accept` already marks the local lane verified, because the Ollama listing showed the model; running `verify` on it confirms that the model loads. Each hosted lane, such as `codex-standard`, is verified the same way, and that launch uses a little of the plan's usage.

## 4. Read the status screen

```bash
jumplane status
```

Each pool shows its window, percent used, reset time and the age of the reading. Each class (light, standard, strong) shows the lane that runs next, or `none open` with up to three `fix:` commands. Output from the run, before any hosted lane was verified:

```text
ollama  local, 5 models at last probe
claude  300m no reading
claude  10080m no reading
codex  10080m 0% resets 6d23h read 0h05m ago (codex-log)

light: next ollama-light (qwen3.5:9b)
standard: none open
  fix: jumplane reading claude --window 10080 --used <percent> --resets-at <epoch>
  fix: jumplane reading claude --window 300 --used <percent> --resets-at <epoch>
  fix: jumplane verify claude-standard
  and 1 more
```

The screen above is cut after the standard class. The Codex reading comes from the Codex session log under `~/.codex` (or `CODEX_HOME`), which jumplane reads even when `JUMPLANE_HOME` points at a scratch folder.

## 5. Pick a lane

The caller states the task's size (`small`, `medium`, `large`), risk and complexity (`low`, `medium`, `high`). A missing value means `medium`. A fixed table turns the shape into a class: high risk or high complexity gives `strong`, all three lowest gives `light`, anything else gives `standard`. The rules' `minimum_class` raises the class when it is higher.

```bash
jumplane pick --size small --risk low --complexity low | tee pick.json
```

Output from the run (the `pick_id` differs on every pick):

```json
{
 "status": "picked",
 "pick_id": "p-6a6cea31a921fee8",
 "lane": "ollama-light",
 "tool": "ollama",
 "model": "qwen3.5:9b",
 "effort": "default",
 "class": "light",
 "reason": "small size, low risk, low complexity gives class light",
 "command": [
  "ollama",
  "run",
  "qwen3.5:9b",
  "<PROMPT>"
 ],
 "stdin": "closed",
 "skipped": [],
 "replayed": false
}
```

`skipped` lists every lane passed over before the one returned, each with its `reasons` and `fixes`. Pass `--request-id <id>` when a caller may retry: after a `picked` answer, the same id with the same shape returns that answer for 600 seconds, marked `"replayed": true`. A `wait` or `unavailable` answer is not stored under the id, so a retry is a fresh pick.

## 6. Launch the command with stdin closed

Replace `<PROMPT>` with your prompt as one argument and run the array as it stands. Close stdin: `ollama run` waits on an open piped stdin, measured at 51 s against 11 s with it closed.

```bash
ollama run --verbose qwen3.5:9b "Reply with the single word ok." < /dev/null 2> stats.txt
tokens=$(awk '/eval count/ {n += $(NF-1)} END {print n}' stats.txt)
echo "$tokens"
```

`--verbose` is an Ollama flag that writes token counts to stderr; the `awk` line adds the prompt and reply counts. Codex prints its own count after `tokens used`. jumplane records whatever count the host gave and does not check it.

## 7. Report the outcome

Take the pick id from the saved answer:

```bash
id=$(sed -n 's/.*"pick_id": "\(p-[0-9a-f]*\)".*/\1/p' pick.json)
```

If you ran another lane than the one picked, record that now, because `override` refuses a pick that is already reported. It takes the pick id, the lane that ran and a reason of up to 200 characters, for example `jumplane override "$id" codex-light --reason "ran on Codex instead"`. The report then counts against the lane that ran. Then report:

```bash
jumplane report "$id" done --tokens "$tokens" --receipt notes/unit-1.md
```

Check: `"status": "recorded"` with the lane, tokens and receipt. The outcome is one of `done`, `failed`, `abandoned` or `limit_hit`. `--receipt` takes one line of up to 500 characters, usually the path of the unit's own record; jumplane stores the text and does not open the file.

`limit_hit` holds the lane's pool. Add `--resets-at <epoch seconds>` when the host showed the reset time; without it the hold lasts until `jumplane release <pool>`.

Reporting the same pick again with the same values returns the stored answer with `"replayed": true`. Different values are refused with exit 2:

```bash
jumplane report "$id" failed
echo "exit $?"
```

## 8. When no lane is open: unavailable and wait

`unavailable` (exit 4) means no lane in the class is open and no known reset would open one. A fresh install shows it for standard work until a hosted lane is verified:

```bash
jumplane pick
echo "exit $?"
```

The answer lists each skipped lane with its reasons, and `fixes` collects the commands that would open one, such as `jumplane verify codex-standard`. jumplane never swaps in a lane from another class.

`wait` (exit 3) means no lane is open now, and at least one lane in the class has only blockers with a known end. A hold with `--until` and a reading over the hold line with a known reset both have one. Other lanes in the class may be blocked for good, for example unverified.

The answer carries `until`, the epoch second at which the first such lane reopens. The run below uses a second scratch folder whose rules hold only the local lane, written by hand:

```bash
export JUMPLANE_HOME="$HOME/jumplane-try/wait-state"
mkdir -p "$JUMPLANE_HOME"
cat > "$JUMPLANE_HOME/rules.json" <<'EOF'
{
 "schema": "jumplane.rules/1",
 "models_as_of": "2026-11-04",
 "minimum_class": "light",
 "hold_at_percent": 90,
 "reserve_percent": 1,
 "lease_seconds": 3600,
 "pools": {"ollama": {"kind": "local"}},
 "lanes": [{"id": "ollama-light", "host": "ollama", "model": "qwen3.5:9b", "effort": "default", "class": "light", "pool": "ollama"}]
}
EOF
jumplane init > /dev/null
jumplane verify ollama-light
jumplane hold ollama --until $(( $(date +%s) + 600 )) --reason "guide example"
jumplane pick --size small --risk low --complexity low
echo "exit $?"
```

The pick answered exit 3 with this, cut after `reason`:

```json
{
 "status": "wait",
 "class": "light",
 "until": 1794300882.0,
 "reason": "no open light lane until a known reset",
```

Here `init` without `--accept` only records which models Ollama serves; it leaves the hand-written rules alone. A lane with any blocker that has no known end, such as being unverified or unread, has no restore time; when every lane in the class is like that, the answer is `unavailable`.

## 9. The same loop from an agent

An agent that runs Python can do the loop in one script. Save it as `loop.py` in the first scratch folder and run `python loop.py` (`python3` on macOS and Linux).

```python
import json
import os
import subprocess

os.environ["JUMPLANE_HOME"] = os.path.expanduser("~/jumplane-try/state")

def jumplane(*args):
    done = subprocess.run(["jumplane", *args], capture_output=True, text=True, encoding="utf-8")
    return done.returncode, json.loads(done.stdout)

code, pick = jumplane("pick", "--size", "small", "--risk", "low", "--complexity", "low")
if pick["status"] != "picked":
    raise SystemExit(f"exit {code}: {pick['status']}, fixes: {pick.get('fixes')}")
argv = ["Reply with the single word ok." if part == "<PROMPT>" else part for part in pick["command"]]
run = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")
outcome = "done" if run.returncode == 0 else "failed"
code, answer = jumplane("report", pick["pick_id"], outcome, "--receipt", "notes/loop.md")
print(code, answer["status"], answer["lane"], answer["outcome"])
```

The script sets `stdin=subprocess.DEVNULL`, which closes stdin, and reads the exit code and JSON of each call.

## Without Ollama

Without a local model, the light class has `codex-light` and `claude-light`. Verify the lanes you have once; each launch sends one short prompt and uses a little of that plan. Then pick:

```bash
jumplane verify codex-light     # with Codex installed
jumplane verify claude-light    # with Claude Code installed
jumplane pick --size small --risk low --complexity low | tee pick.json
id=$(sed -n 's/.*"pick_id": "\(p-[0-9a-f]*\)".*/\1/p' pick.json)
```

A Codex lane opens once jumplane can read a usage figure from the Codex session log, which exists after Codex has run on this machine. A Claude lane opens once the `claude_settings_line` from step 2 is in `~/.claude/settings.json` and a Claude Code session has drawn its status line.

Until then the answer is `unavailable`, and its `fixes` include the `jumplane reading` command that records a figure by hand.

Run the answer's `command` array with `<PROMPT>` replaced and stdin closed. For `codex-light` it is the first line below; run it inside a git repository, because Codex refuses a folder it does not trust. For `claude-light` it is the second line:

```bash
codex exec -m gpt-6-luna -c 'model_reasoning_effort="low"' "Reply with the single word ok." < /dev/null
claude -p --model claude-haiku-5-5 --effort low "Reply with the single word ok." < /dev/null
```

Then report. Codex prints a token count after `tokens used`; add it as `--tokens <count>` to keep it on record. Claude Code in `-p` mode prints only the reply, so leave `--tokens` out:

```bash
jumplane report "$id" done
```

## Exit codes

| Exit | Meaning | Answers |
|---|---|---|
| 0 | Done | `picked`, `recorded`, `proposed`, `accepted`, `verified`, `held`, `released`, `not_held`; `status` and `statusline` print text and exit 0 |
| 2 | Refused input or a failed precondition | `"status": "error"` with the cause in `error`: a bad argument, an unknown pick id, a conflicting repeat report, missing rules |
| 3 | Wait | `wait`, with `until` |
| 4 | No route | `unavailable` from `pick`, or `refused` from `verify` |

Every answer with exit 2 is JSON, so a caller never parses usage text. `statusline` always exits 0, because a status line command must not fail its host.

## Clean up

```bash
rm -rf "$HOME/jumplane-try"
```
