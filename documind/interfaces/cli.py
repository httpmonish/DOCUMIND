"""documind/interfaces/cli.py
Command-line interface adapter for DocuMind.
Provides index, ask, search, ls, rm, and doctor commands.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.metadata
import json
import logging
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from documind.core.config import Settings, load_settings
from documind.core.errors import (
    DocumentTooLarge,
    DocumentUnreadable,
    IndexUnavailable,
    LLMAuthError,
)
from documind.core.pipeline import DocuMind
from documind.core.prompt import build_prompt
from documind.core.serialize import (
    answer_to_dict,
    index_report_to_dict,
    retrieved_to_dict,
)


def get_version() -> str:
    """Retrieve package version or fallback to 0+unknown."""
    try:
        return importlib.metadata.version("documind")
    except Exception:
        return "0+unknown"


def exit_code_for(exc: Exception) -> int:
    """Map exceptions to CLI exit codes."""
    if isinstance(exc, ValueError):
        return 2
    if isinstance(
        exc,
        (
            DocumentUnreadable,
            DocumentTooLarge,
            FileNotFoundError,
            PermissionError,
            IsADirectoryError,
        ),
    ):
        return 4
    if isinstance(exc, (LLMAuthError, ImportError)):
        return 5
    if isinstance(exc, IndexUnavailable):
        return 6
    return 1


def _emit(text: str, stream: TextIO) -> None:
    """Write text to stream with graceful fallback for encoding errors."""
    try:
        stream.write(text + "\n")
        stream.flush()
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", "utf-8") or "utf-8"
        encoded = text.encode(encoding, errors="replace").decode(encoding)
        stream.write(encoded + "\n")
        stream.flush()


def _handle_index(
    args: argparse.Namespace,
    engine: DocuMind,
    stdout: TextIO,
) -> int:
    path = Path(args.path)
    root = Path(args.root) if args.root else None
    report = engine.index(path, root=root)

    if args.json:
        _emit(json.dumps(index_report_to_dict(report)), stdout)
    else:
        for src in report.indexed:
            _emit(f"indexed   {src}", stdout)
        for src in report.skipped:
            _emit(f"skipped   {src}", stdout)
        for src, _reason in report.failed:
            _emit(f"failed   {src}", stdout)
        summary = (
            f"{len(report.indexed)} indexed, {len(report.skipped)} skipped, "
            f"{len(report.failed)} failed, {report.chunks} chunks in {report.seconds:.1f}s"
        )
        _emit(summary, stdout)

    return 4 if report.failed else 0


def _handle_ask(
    args: argparse.Namespace,
    engine: DocuMind,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    top_k = args.top_k
    if top_k is not None and (top_k < 1 or top_k > engine.settings.max_top_k):
        raise ValueError(f"top_k must be between 1 and {engine.settings.max_top_k}, got {top_k}")

    if args.show_prompt:
        hits = engine.search(args.question, top_k=top_k)
        if not hits:
            _emit("No passages retrieved for prompt construction.", stdout)
            return 3
        built = build_prompt(args.question, hits)
        _emit(f"=== SYSTEM PROMPT ===\n{built.system}\n", stdout)
        _emit(f"=== USER PROMPT ===\n{built.user}", stdout)
        return 0

    if args.no_llm:
        engine.llm = None

    ans = engine.answer(args.question, top_k=top_k, interface="cli")

    if args.json:
        d = answer_to_dict(ans, include_retrieved=args.debug)
        _emit(json.dumps(d), stdout)
    else:
        _emit(ans.text, stdout)
        if ans.citations:
            is_retrieval_only = args.no_llm or (ans.abstain_reason == "no_llm")
            header = "Closest passages:" if is_retrieval_only else "Sources:"
            _emit(f"\n{header}", stdout)
            for c in ans.citations:
                _emit(
                    f"[{c.marker}] {c.source}#{c.chunk_index}  ({c.score:.4f})  {c.snippet}",
                    stdout,
                )

    # Stats footer to stderr
    if ans.outcome == "answered":
        status_part = "answered"
    elif ans.abstain_reason:
        status_part = f"abstained: {ans.abstain_reason}"
    else:
        status_part = ans.outcome

    stats = (
        f"({status_part} | {ans.model} | {ans.latency_ms} ms | "
        f"{ans.usage.input_tokens} in / {ans.usage.output_tokens} out)"
    )
    _emit(stats, stderr)

    if ans.outcome == "answered" or ans.abstain_reason == "no_llm":
        return 0
    return 3


def _handle_search(
    args: argparse.Namespace,
    engine: DocuMind,
    stdout: TextIO,
) -> int:
    top_k = args.top_k
    if top_k is not None and (top_k < 1 or top_k > engine.settings.max_top_k):
        raise ValueError(f"top_k must be between 1 and {engine.settings.max_top_k}, got {top_k}")

    hits = engine.search(args.question, top_k=top_k)
    if not hits:
        if args.json:
            _emit("[]", stdout)
        else:
            _emit("No matching passages found.", stdout)
        return 3

    if args.json:
        rows = [retrieved_to_dict(h, include_text=args.debug) for h in hits]
        _emit(json.dumps(rows), stdout)
    else:
        for h in hits:
            snippet = h.chunk.text[:200]
            _emit(
                f"{h.rank}. {h.chunk.source}#{h.chunk.chunk_index} ({h.score:.4f}) {snippet}",
                stdout,
            )
    return 0


def _handle_ls(
    args: argparse.Namespace,
    engine: DocuMind,
    stdout: TextIO,
) -> int:
    docs = engine.documents()
    if not docs:
        if args.json:
            _emit("[]", stdout)
        else:
            _emit("No documents indexed.", stdout)
        return 0

    if args.json:
        rows = [{"source": src, "chunks": engine.chunk_count(src)} for src in docs]
        _emit(json.dumps(rows), stdout)
    else:
        for src in docs:
            count = engine.chunk_count(src)
            _emit(f"{count:>5}  {src}", stdout)
    return 0


def _handle_rm(
    args: argparse.Namespace,
    engine: DocuMind,
    stdout: TextIO,
    stderr: TextIO,
    is_tty: bool,
) -> int:
    source = args.source
    indexed_docs = engine.documents()
    if source not in indexed_docs:
        _emit(f"error: source '{source}' is not indexed", stderr)
        return 4

    if not args.yes:
        if not is_tty:
            _emit("error: rm requires --yes flag in non-interactive environment", stderr)
            return 2
        try:
            choice = input(f"Remove '{source}' and all its indexed chunks? [y/N]: ").strip().lower()
        except EOFError:
            _emit("error: EOF encountered during confirmation", stderr)
            return 2
        if choice not in {"y", "yes"}:
            _emit("Aborted.", stderr)
            return 0

    removed = engine.delete(source)
    _emit(f"removed {removed} chunks for {source}", stdout)
    return 0


def _handle_doctor(
    args: argparse.Namespace,
    settings: Settings,
    stdout: TextIO,
) -> int:
    from documind.core.doctor import (
        check_api_key,
        check_extras,
        check_home,
        check_meta,
        check_python,
        exit_code,
    )

    checks = [
        check_python((sys.version_info.major, sys.version_info.minor, sys.version_info.micro)),
        check_api_key(os.environ),
        check_home(settings.home),
        check_meta(settings.home, settings.embed_model),
        *check_extras(),
    ]

    if args.json:
        rows = [
            {
                "name": c.name,
                "status": c.status,
                "detail": c.detail,
                "category": c.category,
            }
            for c in checks
        ]
        _emit(json.dumps(rows), stdout)
    else:
        for c in checks:
            _emit(f"[{c.status}] {c.name}: {c.detail}", stdout)

    return exit_code(checks)


def _handle_stats(
    args: argparse.Namespace,
    settings: Settings,
    stdout: TextIO,
) -> int:
    from documind.core.stats import aggregate_query_logs

    log_path = settings.home / "logs" / "queries.jsonl"
    stats_data = aggregate_query_logs(log_path, days=args.days)

    if args.json:
        _emit(json.dumps(stats_data), stdout)
        return 0

    if stats_data["query_count"] == 0:
        _emit("No query logs found.", stdout)
        return 0

    _emit("=== DOCUMIND QUERY STATISTICS ===", stdout)
    _emit(f"Total queries: {stats_data['query_count']}", stdout)
    _emit(f"Total cost:    ${stats_data['total_cost_usd']:.4f}", stdout)

    p50 = (
        f"{stats_data['latency_p50_ms']} ms" if stats_data["latency_p50_ms"] is not None else "n/a"
    )
    p95 = (
        f"{stats_data['latency_p95_ms']} ms" if stats_data["latency_p95_ms"] is not None else "n/a"
    )
    _emit(f"Latency:       p50={p50}, p95={p95}", stdout)

    _emit("\nOutcomes:", stdout)
    for outcome, cnt in stats_data["outcomes"].items():
        _emit(f"  {outcome:<15}: {cnt}", stdout)

    if stats_data["abstain_reasons"]:
        _emit("\nAbstention reasons:", stdout)
        for reason, cnt in stats_data["abstain_reasons"].items():
            _emit(f"  {reason:<15}: {cnt}", stdout)

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser with subcommands and options."""
    parser = argparse.ArgumentParser(
        prog="documind",
        description="DocuMind: Local-first grounded document QA and search engine.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"documind {get_version()}",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help="Override DocuMind home directory (DOCUMIND_HOME)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging and show tracebacks on internal errors",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # index
    p_index = subparsers.add_parser("index", help="Index documents from file or directory")
    p_index.add_argument("path", type=str, help="Path to document file or directory")
    p_index.add_argument("--root", type=str, default=None, help="Root directory for relative paths")
    p_index.add_argument("--json", action="store_true", help="Output machine-readable JSON report")

    # ask
    p_ask = subparsers.add_parser("ask", help="Ask a question grounded in indexed documents")
    p_ask.add_argument("question", type=str, help="User question string")
    p_ask.add_argument("--top-k", type=int, default=None, help="Number of retrieved passages")
    p_ask.add_argument("--json", action="store_true", help="Output machine-readable JSON answer")
    p_ask.add_argument("--no-llm", action="store_true", help="Skip LLM generation, return passages")
    p_ask.add_argument(
        "--show-prompt", action="store_true", help="Print constructed prompt and exit"
    )

    # search
    p_search = subparsers.add_parser("search", help="Perform semantic retrieval search")
    p_search.add_argument("question", type=str, help="Search query")
    p_search.add_argument("--top-k", type=int, default=None, help="Number of passages")
    p_search.add_argument("--json", action="store_true", help="Output results as JSON")

    # ls
    p_ls = subparsers.add_parser("ls", help="List indexed documents")
    p_ls.add_argument("--json", action="store_true", help="Output document list as JSON")

    # rm
    p_rm = subparsers.add_parser("rm", help="Remove an indexed document")
    p_rm.add_argument("source", type=str, help="Document source identifier to delete")
    p_rm.add_argument("--yes", "-y", action="store_true", help="Confirm deletion without prompting")

    # doctor
    p_doctor = subparsers.add_parser("doctor", help="Run installation and index diagnostic checks")
    p_doctor.add_argument("--json", action="store_true", help="Output diagnostic checks as JSON")

    # stats
    p_stats = subparsers.add_parser("stats", help="Show query log statistics and volume")
    p_stats.add_argument("--days", type=float, default=None, help="Filter to last N days")
    p_stats.add_argument("--json", action="store_true", help="Output stats as JSON")

    return parser


def main(
    argv: list[str] | None = None,
    *,
    engine_factory: Callable[[Settings], DocuMind] | None = None,
    settings: Settings | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    is_tty: bool | None = None,
) -> int:
    """Main CLI entrypoint."""
    stdout_stream = stdout if stdout is not None else sys.stdout
    stderr_stream = stderr if stderr is not None else sys.stderr

    tty = is_tty if is_tty is not None else (hasattr(sys.stdin, "isatty") and sys.stdin.isatty())

    parser = build_parser()

    # Parse arguments
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    if not args.command:
        parser.print_usage(stderr_stream)
        return 2

    # Configure logging strictly to stderr
    log_level = logging.DEBUG if args.debug else logging.WARNING
    logging.basicConfig(level=log_level, stream=stderr_stream, force=True)

    # Load configuration
    cfg = settings or load_settings()
    if args.home:
        cfg = dataclasses.replace(cfg, home=Path(args.home))

    try:
        if args.command == "doctor":
            return _handle_doctor(args, cfg, stdout_stream)
        if args.command == "stats":
            return _handle_stats(args, cfg, stdout_stream)

        # Build engine lazily
        if engine_factory is not None:
            engine = engine_factory(cfg)
        else:
            from documind.core.factory import build_default

            engine = build_default(cfg)

        if args.command == "index":
            return _handle_index(args, engine, stdout_stream)
        elif args.command == "ask":
            return _handle_ask(args, engine, stdout_stream, stderr_stream)
        elif args.command == "search":
            return _handle_search(args, engine, stdout_stream)
        elif args.command == "ls":
            return _handle_ls(args, engine, stdout_stream)
        elif args.command == "rm":
            return _handle_rm(args, engine, stdout_stream, stderr_stream, tty)
        else:
            parser.print_usage(stderr_stream)
            return 2

    except Exception as exc:
        code = exit_code_for(exc)
        if code == 1:
            _emit("error: internal error (re-run with --debug for details)", stderr_stream)
            if args.debug:
                traceback.print_exc(file=stderr_stream)
        else:
            _emit(f"error: {exc}", stderr_stream)
        return code
