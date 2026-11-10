# The event log

jumplane appends one JSON object per line to `events.jsonl` in its state folder (`~/.jumplane`, or `JUMPLANE_HOME`). The code only appends to it. It is the audit record: what was picked and why, what was passed over, what each unit reported, and every hold, override and hand-entered reading.

## Events and their fields

Every line has `kind` and `at` (epoch seconds). The other fields:

| `kind` | Written by | Fields |
|---|---|---|
| `rules_accepted` | `init --accept` | `lanes`: lane ids in the accepted rules |
| `picked` | `pick` | `pick_id`, `lane`, `wanted` (class), `skipped` (lane ids passed over) |
| `wait`, `unavailable` | `pick` | `wanted`, `skipped` |
| `reported` | `report` | `pick_id`, `lane`, `outcome`, `tokens`, `receipt` |
| `override` | `override` | `pick_id`, `before`, `after`, `reason` |
| `hold` | `hold` | `pool`, `until` |
| `release` | `release` | `pool` |
| `reading` | `reading` (by hand) | `pool`, `window`, `used`, `resets_at`, `source` |
| `verify` | `verify` | `lane`, `ok` |

Readings taken from the Claude Code status line and the Codex log update `state.json` only, so they leave no event line. A `limit_hit` report holds the pool inside the `reported` event and writes no separate `hold` line.

## A recorded example

These two lines come from the recorded session of 10 Nov 2026, with the receipt path cut to its file name. In that session a Claude pool at 15 percent of its weekly window was held against a 10 percent hold line and the pick moved to Codex:

```json
{"at": 1794294282.4398944, "kind": "picked", "lane": "codex-standard", "pick_id": "p-888b116fcffb5d33", "skipped": ["claude-standard"], "wanted": "standard"}
{"at": 1794299903.71371, "kind": "reported", "lane": "codex-standard", "outcome": "done", "pick_id": "p-888b116fcffb5d33", "receipt": "SESSION-hold-move-launch-2026-11-10.md", "tokens": 5130}
```

The reasons for each skipped lane are in the `pick` answer the caller received, not in the event line. A caller that needs them on record keeps the answer, for example as the receipt file.

## What it holds and what it does not

The readers take only limit fields: percent used, window length and reset time. jumplane itself writes no prompt, reply, file content or API key to the log.

Callers supply two free-text fields that are stored verbatim: the `report --receipt` text and the `override --reason` text. Keep secrets, prompts and personal data out of both; a receipt is best a path or an id.

## Reading it

The file is plain JSON lines, so any JSON tool reads it. This counts outcomes per lane with the Python standard library:

```bash
python -c "import collections, json, os, pathlib; home = pathlib.Path(os.environ.get('JUMPLANE_HOME') or pathlib.Path.home() / '.jumplane'); rows = [json.loads(l) for l in open(home / 'events.jsonl', encoding='utf-8')]; print(collections.Counter((r['lane'], r['outcome']) for r in rows if r['kind'] == 'reported'))"
```

## Limits

- The file is plain text. Any program running as your user can edit or delete lines, and jumplane does not detect it. A hash chain per line would make edits evident; it is proposed and not built.
- `outcome`, `tokens` and `receipt` are written by the caller, often an agent, and jumplane does not check them.
- The log is never rotated or trimmed. `state.json` keeps only the last 1,000 closed picks; the log keeps every line.
- There is no summary command yet. A planned `jumplane audit` would count picks, outcomes, overrides and tokens per lane.
