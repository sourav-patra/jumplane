# Decisions

Each line is a ruling the build follows. Newest last. Change one only by adding a new line that names the one it replaces.

| Date | Id | Decision | Why |
|---|---|---|---|
| 2026-11-03 | first-release | One research-based first public release replaces both earlier drafts (a three-day 0.1 and the 0.4 spec). | Neither gave a stranger a working route, a console and labels that steer a pick. |
| 2026-11-04 | clean-room | `pick`, pools and holds are designed from the release definition and public precedents only. No text from any other project enters this tree. Reaffirmed 2026-11-07. | Provenance of a public release. |
| 2026-11-04 | orphan | The build lives on an orphan branch, so no older labeller, import shim or old schema sits in the history a public export is cut from. | The export is one clean commit. |
| 2026-11-04 | name | Public name `jumplane`, site jumplane.dev. | Free on PyPI and npm on 3 Nov. |
| 2026-11-04 | rollover | A reading counts as zero used for one window after its known reset. | Otherwise no host could run to refresh the reading. |
| 2026-11-04 | stdin | Pick answers say `stdin: closed`, and callers launch with stdin closed. | `ollama run` waits on an open piped stdin: measured 51 s against 11 s. |
| 2026-11-04 | defaults | `init` proposes a hold at 90 percent used, a 1 percent reservation per pick and a 3600 s lease. | Starting values, not measured. |
| 2026-11-07 | outcomes | Report outcomes stay `done`, `failed`, `abandoned`, `limit_hit`. `pick` statuses add `wait` and `unavailable`, which carry no pick id. | Closed values that callers can count. |
| 2026-11-07 | report-fields | `report` takes `--tokens` and `--receipt`. A repeated report returns the stored values and refuses different ones. | Callers record one dispatch line per unit from the answer. |
| 2026-11-07 | json-errors | Every refused argument answers with the JSON error and exit 2. | Callers parse stdout only. |

## Behaviour rules

- A pool with no reading is unavailable unless the rules set `allow_unread` for it. A hold beats any reading.
- A local pool is eligible while its last probe succeeded. `pick` never opens a socket.
- The caller passes size, risk and complexity. Missing means medium. The rules set an owner minimum class.
- Ties go to the order in the rules file.
- A stale or unverified route is refused with the command that would verify it, never silently replaced.
- `pick` answers `wait` only when a known reset would restore a lane; otherwise `unavailable` with fixes.
- One request id answers once for 600 s. Reservations expire by lease. jumplane does not stop two callers from running the same work.
