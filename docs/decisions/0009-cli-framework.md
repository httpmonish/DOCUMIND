# ADR 0009: CLI Framework and Startup Discipline

## Context
DocuMind needs a CLI interface (`documind`) supporting subcommands: `index`, `ask`, `search`, `ls`, `rm`, `doctor`, and `stats`. In local environments, command-line interfaces must start instantaneously for diagnostic and help queries, cleanly separate structured data streams from diagnostics, and run reliably across various platforms (Linux, macOS, and Windows cmd/PowerShell).

## Options Considered

1. **`argparse` (Standard Library)**
   - Extra dependencies: 0
   - Cumulative import time: ~97 ms
   - Cold execution (`documind --help`): ~0.10s
   - Wheel package size impact: 0 KB

2. **`click` (BSD-3)**
   - Extra dependencies: +1 (`click`)
   - Import overhead: adds ~30–50 ms
   - Decorator-driven ergonomics, but introduces dependency management surface.

3. **`typer` (MIT)**
   - Extra dependencies: +2 (`typer`, `click`, optional `shellingham`, `rich`)
   - Cold start overhead: noticeably higher import time and deeper dependency graph.

## Decision
Adopt Python standard library `argparse` for the `documind` command-line interface.

All heavy modules (`torch`, `sentence_transformers`, `chromadb`, `anthropic`) are strictly lazily imported inside command handlers or `build_default()` only when an active engine instance is required. Subcommands like `--help`, `--version`, and `doctor` avoid loading ML dependencies altogether.

Furthermore, stream discipline is enforced:
- `stdout`: Reserved exclusively for primary results (plain answer, tabular lists, or valid JSON).
- `stderr`: Dedicated to logs, progress, error notices, and query performance footers.
- Console encoding degradation handles systems lacking UTF-8 support (replacing unencodable characters instead of crashing).

## Trade-offs: You Give Up X to Get Y
- **You give up:** Click/Typer decorator ergonomics and automatic shell autocompletion.
- **To get:** Zero new runtime dependencies, sub-105ms `--help` execution, and resilient packaging.

## Revisit When
Revisit if CLI requirements grow to 20+ deeply nested subcommands or complex interactive prompt workflows where `click`'s parameter types and shell completion justify the dependency and startup overhead.
