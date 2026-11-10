"""Frozen launch models for this release. `init` proposes them; the owner accepts once."""

MODELS_AS_OF = "2026-11-04"
ROUTES = [
    ("claude-light", "claude", "claude-haiku-5-5", "low", "light"),
    ("claude-standard", "claude", "claude-sonnet-5-5", "medium", "standard"),
    ("claude-strong", "claude", "claude-opus-5-5", "high", "strong"),
    ("codex-light", "codex", "gpt-6-luna", "low", "light"),
    ("codex-standard", "codex", "gpt-6.1-terra", "medium", "standard"),
    ("codex-strong", "codex", "gpt-6.1-sol", "high", "strong"),
]
WINDOWS = {"claude": [300, 10080], "codex": [10080]}
