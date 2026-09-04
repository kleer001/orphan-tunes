# you_tunes_browser

TODO: describe you_tunes_browser

## Quick commands

- Activate env: `source .venv/bin/activate`
- Install deps: `pip install -e ".[dev]"`
- Run: `python main.py`
- Test: `pytest`
- Lint/format: `ruff check . && ruff format .`

## Project structure

- `main.py` — entry point
- `tests/` — pytest test suite
- `pyproject.toml` — metadata, deps, tool config
- `.scaffold.json` — record of how this repo was generated (do not edit by hand)

## Testing

Run `pytest` from repo root. Tests live in `tests/`. New features need at least one test that fails before the change and passes after.

## Code style

- `ruff` is the linter and formatter — config in `pyproject.toml`.
- Naming: `snake_case` functions/vars, `PascalCase` classes.
- Imports: stdlib → third-party → local.
- Comments: explain *why*, not *what*. Skip them on self-evident code.

## Git

Atomic commits. Conventional Commits: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`.

## Boundaries

- Don't touch `.scaffold.json` by hand.
- Trust internal functions; validate at boundaries (CLI args, file inputs, network responses).
- One path, no fallbacks. Fail loudly. (See `~/.claude/CLAUDE.md` for the full philosophy.)
