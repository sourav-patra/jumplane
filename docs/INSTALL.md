# Install

jumplane needs Python 3.11 or newer and nothing else at run time. It installs from PyPI. To pin the source instead, install from a git tag: `uv tool install git+https://github.com/sourav-patra/jumplane@v0.1.1`.

## macOS or Linux

```bash
brew install uv            # or: curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install jumplane
jumplane --version
jumplane init              # detects Claude Code, Codex and Ollama, proposes rules
jumplane init --accept     # writes the rules after you read them
jumplane status
```

uv downloads its own Python when the system one is older than 3.11.

## Windows (PowerShell or Git Bash)

```powershell
winget install astral-sh.uv
uv tool install jumplane
jumplane --version
jumplane init
jumplane init --accept
jumplane status
```

The CI workflow runs the tests on Windows, Linux and macOS. Before the first public CI run, the tests and daily use were checked on Windows 11 only.

## Claude Code usage readings

Claude Code reports usage only through its status line. `jumplane init` prints the line to add to `~/.claude/settings.json`; it writes no host file itself. Without it the Claude pool is unread and therefore unavailable.

## Next

Run the loop in [guide.md](guide.md): `verify`, `pick`, launch, `report`.

## Update and remove

```bash
uv tool upgrade jumplane
uv tool uninstall jumplane
```

State lives in `~/.jumplane` (or `JUMPLANE_HOME`). Uninstalling leaves it in place; delete the folder to remove it.
