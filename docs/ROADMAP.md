# Roadmap

Status on 2026-11-10: pre-release on branch `jumplane/first-release`. Nothing is published.

## First public release

| Milestone | Contents | State |
|---|---|---|
| 1 | Package, store, rules, shape table, `pick`, `report`, `override`, `init` | Done |
| 2 | Claude status line reader, Codex log reader, `status`, `statusline` | Done |
| 2 | Local Ollama pool; a recorded hold, move and launch (10 Nov) | Done |
| 2 | Claude reading compared with the host display | Open |
| 3 | Guide, README with two figures, limits, event log and local-lane pages, CI workflow files (first GitHub run pending) | Done |
| 3 | Independent review, reader check, release runbook | Open |

Target: release ready on 2026-11-11. This is an estimate, and each extra review round adds 1 to 2 hours.

Scope of `v0.1.0`, set by the owner on 10 Nov 2026: the commands above, installed from a pinned git tag. Not in `v0.1.0`: `lock`, MCP, OpenCode and a PyPI package. All four come after the first release.

The release must show:

- a recorded real session: a reading crosses the threshold, `pick` holds that pool and returns another lane, and the returned command runs on that host;
- the readers checked against what each host shows;
- a README that says plainly: rule based, not a quality predictor, no benchmark run yet, log readers rest on undocumented formats and fall back to "no reading".

## After the first release

- `lock`: rules signed with `ssh-keygen -Y`.
- MCP server limited to `pick`, `report` and `override`.
- OpenCode as a third host (pick only).
- PyPI package through Trusted Publisher.
- Hosted labeller and benchmark run.
- Attempts and metered settlement for API pools.
- Refreshed model evidence in place of the frozen model table.
- A classifier arm that suggests a lane, admitted only after a benchmark.
- Trust files owned by another account, a stronger boundary than signing.
