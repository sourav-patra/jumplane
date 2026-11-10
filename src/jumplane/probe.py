"""Host detection for `init` and `verify`. The only module that may open a socket, and only to loopback."""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
VERIFY_SECONDS = 180
VERIFY_PROMPT = "Reply with the single word OK."


def host_present(host: str) -> bool:
    return shutil.which(host) is not None


LOOPBACK = ("127.0.0.1", "localhost", "::1")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a redirect becomes an HTTPError, so the probe never leaves the address it was given


# No proxy from the environment and no redirects: the request goes straight to the loopback address.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def ollama_models(url: str = OLLAMA_TAGS, timeout: float = 2.0) -> list[str] | None:
    """Local model names, or None when the server does not answer. Cloud-backed and embedding tags cannot run a task here, so they are left out."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in LOOPBACK:
        return None
    try:
        with _OPENER.open(url, timeout=timeout) as response:
            names = [m["name"] for m in json.load(response)["models"]]
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        return None
    return [n for n in names if not n.endswith(":cloud") and "embed" not in n and not n.startswith("bge-")]


def run_verify(command: list[str]) -> tuple[bool, str]:
    """Launch the route once with a trivial prompt. Uses a small amount of the host's usage."""
    executable = shutil.which(command[0])
    if executable is None:
        return False, f"{command[0]} is not on PATH"
    argv = [executable, *[VERIFY_PROMPT if part == "<PROMPT>" else part for part in command[1:]]]
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=VERIFY_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if done.returncode:
        return False, f"exit {done.returncode}: {done.stderr.strip()[-300:]}"
    return True, "launched"
