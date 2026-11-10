# AGENTS.md

1. Standard library only.
2. No model output selects a route. Routes come from the rules file and code.
3. Only `probe.py` may open a socket or start a process, and its socket goes to loopback only. `pick` does neither.
4. Run before saying anything works, from the repository root:
   `PYTHONPATH=src python -m unittest discover -s tests -t .`
5. Documentation follows the "Writing docs" section of CONTRIBUTING.md. Run `python scripts/readme_lint.py README.md` before proposing a README change.
