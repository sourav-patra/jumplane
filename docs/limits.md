# Status and limits

Status on 10 Nov 2026: pre-release `v0.1.0`. Every figure below comes from one Windows 11 PC on that day, unless a line says otherwise.

## Built, not built, not measured

| Built and tested | Not built | Not measured |
|---|---|---|
| `init`, `verify`, `pick`, `report`, `override`, `hold`, `release`, `status`, `statusline`, `reading` | Signed rules (`lock`) | Whether a pick beats the host's default on quality, cost or completed work; no benchmark has run |
| Claude Code status line reader | MCP server | Setup time for a new user |
| Codex session log reader | OpenCode as a host | Behaviour on macOS and Linux; the tests have run on Windows only until the first CI run |
| Local Ollama pool | Budgets in money for metered APIs | Claude reader accuracy against the host's own display |
| Event log | `jumplane audit` and `jumplane tune` | Savings of any kind |

## Measured

| Fact | Value | How |
|---|---|---|
| Tests | 78 pass (Python 3.11 and 3.13) | `PYTHONPATH=src python -m unittest discover -s tests -t .` |
| Runtime dependencies | 0 | `dependencies = []` in `pyproject.toml`, held by the test `test_standard_library_only` |
| Hold and move | A Claude pool at 15% of its weekly window, against a 10% hold line, was passed over; the pick returned `codex-standard`; that command exited 0 after 6 s using 5,130 tokens | the recorded session in the [README figure](../README.md) |
| Local models | 5 of 5 answered `jumplane verify`, in 19 to 53 s | [local-lanes.md](local-lanes.md) |

## Limits

- jumplane is rule based. It does not predict quality, and it never reads a prompt to choose a lane.
- The caller states the task shape. A caller can understate it, down to the `minimum_class` the rules set.
- The hold line applies to every window the rules list for a pool and to any other window with a valid stored reading. Codex can log a 300-minute window as well as the weekly one; the default rules list only the weekly window, so a missing 300-minute reading never blocks, while an exhausted one holds the Codex pool until its reset.
- The Codex reader rests on an undocumented log format. A missing log or any surprise in it yields no new reading. The last good reading stays in use: it counts until its reset, then as zero used for one more window, then expires. After that the Codex pool is unavailable until Codex writes a readable log line or a reading is recorded by hand.
- Claude Code exposes its limits only through its status line. Without the settings line that `init` prints, the Claude pool has no reading and stays unavailable.
- A reading counts as valid until its reset, then as zero used for one more window, then expires. A reading taken days ago can still open or close a lane.
- jumplane cannot switch a session that is already running. It acts at the next `pick`.
- jumplane does not stop two callers from running the same work. A request id makes a retried pick return the first `picked` answer for 600 s. A `wait` or `unavailable` answer is not stored, so a retry after one is a fresh pick.
- The hold line (90% by default), the 1% reservation per pick and the 3,600 s lease are starting values, not measured ones.
- The event log and the rules file are plain files that any program running as your user can edit. See [events.md](events.md).
- The launch models are a table frozen on 4 Nov 2026. `status` warns when it is over 30 days old, and the warning does not change the ranking.
- Only terminal users are served. There is no chat or desktop surface.
