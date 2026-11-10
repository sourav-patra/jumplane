# Security

## Supported versions

| Version | Security fixes |
|---|---|
| 0.1.x (pre-release) | Yes |
| Older development builds | No |

## Report a vulnerability

Report it privately through GitHub: open the repository's Security tab and choose "Report a vulnerability". Do not open a public issue for a vulnerability. Include the jumplane version (`jumplane --version`), your operating system, the commands you ran and what happened.

The maintainer is one person working in spare time. A first answer within 7 days is the aim, not a guarantee.

## What jumplane touches

These are the boundaries a report would show broken. Each is enforced by code or a test in `tests/`.

- `pick`, `report`, `override`, `hold`, `release`, `status` and `reading` open no socket and start no process. Only `src/jumplane/probe.py` does either, for `init` and `verify`.
- `probe.py` connects to `127.0.0.1:11434` only, to list local Ollama models. It refuses any address other than `127.0.0.1`, `localhost` or `::1`, ignores proxy settings and follows no redirect (tests `test_probe_refuses_addresses_off_loopback` and `test_probe_refuses_a_redirect_and_ignores_proxy_settings`).
- `verify` starts the lane's own command once (`claude`, `codex` or `ollama`) with a fixed short prompt and stdin closed.
- jumplane holds no API keys and sends no telemetry. It reads limit fields from the Claude Code status line input and the Codex session log; it never stores prompts or replies.
- State lives in `~/.jumplane` (or `JUMPLANE_HOME`): `rules.json`, `state.json` and `events.jsonl`. Any program running as your user can edit these files. The rules file is not signed in 0.1.x.
