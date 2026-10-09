# Contributing to DocuMind

## Development Setup

1. **Create and activate a virtual environment (Python >= 3.10):**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Install editable package with development and embedding extras:**
   ```bash
   pip install -e ".[dev,embed]"
   ```

3. **Install pre-commit hooks:**
   ```bash
   pre-commit install
   ```

## Architectural Boundaries

- **`core/` never imports from an interface.** Everything in `documind/core/` must remain decoupled from `documind/interfaces/` (CLI, REST, MCP). Interfaces are thin adapters that call `DocuMind`.
- **Stream Discipline:** CLI stdout is strictly reserved for primary results (answers, tables, JSON). All warnings, logs, stats, and tracebacks must go to `stderr`.
- **Lazy Imports:** Never import heavy ML frameworks (`torch`, `sentence_transformers`, `chromadb`, `anthropic`) at module root in `documind.interfaces.cli`.

## Testing & Quality Gates

Run the standard offline test suite before opening any PR:

```bash
ruff check .
ruff format --check .
mypy documind
pytest -m "not slow and not live" --cov=documind --cov-fail-under=85
```

## Commit Discipline

Follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat(scope): imperative summary <= 72 characters`
- `fix(scope): fix description`
- `test(scope): test description`
- `docs(scope): documentation update`
- Keep commits atomic: commit tests alongside the implementation they verify.
