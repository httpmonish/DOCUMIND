"""tests/test_cli.py -- the command-line adapter, tested without a model,
a network or a real index.
"""

from __future__ import annotations

import dataclasses
import io
import json
import logging
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from documind.core.errors import (
    DocumentTooLarge,
    DocumentUnreadable,
    IndexUnavailable,
    LLMAuthError,
)
from documind.core.vector_store import NumpyStore
from documind.interfaces.cli import exit_code_for, main
from tests.engine_helpers import make_engine

ROOT = Path(__file__).resolve().parent.parent
SEM = "what is a semaphore"


def run_cli(argv, engine, *, tty=False, settings=None):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(
            argv,
            engine_factory=lambda cfg: engine,
            settings=settings or engine.settings,
            stdout=out,
            stderr=err,
            is_tty=tty,
        )
    return code, out.getvalue(), err.getvalue()


def test_version_and_help_and_missing_command(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore())
    code, out, _ = run_cli(["--version"], eng)
    assert code == 0 and out.startswith("documind ") and len(out.split()[1]) > 0
    code, out, _ = run_cli(["--help"], eng)
    assert code == 0 and all(w in out for w in ("index", "ask", "search", "ls", "rm", "doctor"))
    code, _, err = run_cli([], eng)
    assert code == 2 and "usage" in err.lower()


def test_ask_answered_prints_answer_and_sources_to_stdout_and_stats_to_stderr(tmp_path):
    eng, llm, _ = make_engine(tmp_path, NumpyStore())
    code, out, err = run_cli(["ask", SEM], eng)
    assert code == 0
    assert "A semaphore is a counter. [S1]" in out and "Sources" in out and "os.md#0" in out
    assert "answered" in err and "1700 in / 300 out" in err and "Sources" not in err
    assert len(llm.calls) == 1


def test_ask_abstains_with_exit_code_3(tmp_path):
    eng, llm, _ = make_engine(tmp_path, NumpyStore())
    code, out, _ = run_cli(["ask", "who won the 2022 football world cup"], eng)
    assert code == 3 and out.strip() != "" and len(llm.calls) == 0


def test_ask_on_an_empty_index_exits_3(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=False)
    code, out, _ = run_cli(["ask", SEM], eng)
    assert code == 3 and "indexed" in out.lower()


def test_ask_json_stdout_is_only_json_even_when_something_logs(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore())

    def noisy_factory(cfg):
        logging.getLogger("noise").warning("this must go to stderr")
        return eng

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(
            ["ask", SEM, "--json"],
            engine_factory=noisy_factory,
            settings=eng.settings,
            stdout=out,
            stderr=err,
            is_tty=False,
        )
    d = json.loads(out.getvalue())  # raises if anything else reached stdout
    assert code == 0 and d["outcome"] == "answered" and d["citations"][0]["source"] == "os.md"
    assert "retrieved" not in d and "this must go to stderr" in err.getvalue()


def test_no_llm_returns_passages_with_exit_0_and_makes_no_call(tmp_path):
    eng, llm, _ = make_engine(tmp_path, NumpyStore())
    code, out, _ = run_cli(["ask", SEM, "--no-llm"], eng)
    assert code == 0 and "Closest passages" in out and "os.md#0" in out and len(llm.calls) == 0


def test_show_prompt_prints_the_exact_prompt_and_makes_no_call(tmp_path):
    eng, llm, _ = make_engine(tmp_path, NumpyStore())
    code, out, _ = run_cli(["ask", SEM, "--show-prompt"], eng)
    assert code == 0 and "<sources>" in out and 'id="S1"' in out
    assert "<question>" in out and len(llm.calls) == 0


def test_bad_top_k_is_a_usage_error(tmp_path):
    eng, llm, _ = make_engine(tmp_path, NumpyStore())
    code, _, err = run_cli(["ask", SEM, "--top-k", "11"], eng)
    assert code == 2 and "top_k" in err and len(llm.calls) == 0


def test_search_lists_ranked_chunks(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore())
    code, out, _ = run_cli(["search", SEM, "--top-k", "2"], eng)
    assert code == 0 and out.splitlines()[0].startswith("1. ") and "os.md#0" in out
    code, out, _ = run_cli(["search", SEM, "--json"], eng)
    rows = json.loads(out)
    assert code == 0 and rows[0]["rank"] == 1
    assert rows[0]["source"] == "os.md" and "text" not in rows[0]


def test_index_a_directory_reports_failures_and_exits_4(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text(" ".join(f"w{i}" for i in range(300)), encoding="utf-8")
    (docs / "b.txt").write_text("a short note about paging", encoding="utf-8")
    (docs / "bad.pdf").write_bytes(b"not a pdf")
    eng, _, _ = make_engine(tmp_path / "home", NumpyStore(), fill=False)
    code, out, _ = run_cli(["index", str(docs)], eng)
    assert code == 4 and "2 indexed, 0 skipped, 1 failed" in out and "failed   bad.pdf" in out
    code, out, _ = run_cli(["ls"], eng)
    assert code == 0 and "a.md" in out and "b.txt" in out and "bad.pdf" not in out
    code, out, _ = run_cli(["ls", "--json"], eng)
    assert {r["source"]: r["chunks"] for r in json.loads(out)} == {"a.md": 2, "b.txt": 1}
    (docs / "bad.pdf").unlink()
    code, out, _ = run_cli(["index", str(docs), "--json"], eng)  # second run: everything unchanged
    d = json.loads(out)
    assert code == 0 and d["indexed"] == []
    assert sorted(d["skipped"]) == ["a.md", "b.txt"] and d["failed"] == []


def test_index_of_a_missing_path_exits_4(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=False)
    code, _, err = run_cli(["index", str(tmp_path / "nope.md")], eng)
    assert code == 4 and err.startswith("error:")


def test_ls_on_an_empty_index(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=False)
    code, out, _ = run_cli(["ls"], eng)
    assert code == 0 and "No documents indexed." in out


def test_rm_requires_confirmation(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore())
    code, _, err = run_cli(["rm", "os.md"], eng, tty=False)  # non-interactive without --yes
    assert code == 2 and "--yes" in err and eng.documents() == ["os.md"]
    with patch("builtins.input", return_value="n"):
        code, _, _ = run_cli(["rm", "os.md"], eng, tty=True)
    assert code == 0 and eng.documents() == ["os.md"]  # declined: nothing removed
    with patch("builtins.input", return_value="y"):
        code, out, _ = run_cli(["rm", "os.md"], eng, tty=True)
    assert code == 0 and "removed 2 chunks" in out and eng.documents() == []
    code, _, err = run_cli(["rm", "os.md", "--yes"], eng)
    assert code == 4 and "not indexed" in err


def test_home_flag_overrides_the_settings_home(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore())
    seen = []

    def factory(cfg):
        seen.append(cfg)
        return eng

    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["--home", str(tmp_path / "elsewhere"), "ls"],
        engine_factory=factory,
        settings=eng.settings,
        stdout=out,
        stderr=err,
        is_tty=False,
    )
    assert code == 0 and seen[0].home == tmp_path / "elsewhere"


def test_unexpected_errors_are_hidden_unless_debug(tmp_path):
    def boom(cfg):
        raise RuntimeError("kaboom")

    for argv, want_trace in ((["ls"], False), (["--debug", "ls"], True)):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                argv,
                engine_factory=boom,
                settings=make_engine(tmp_path, NumpyStore())[0].settings,
                stdout=out,
                stderr=err,
                is_tty=False,
            )
        assert code == 1 and "internal error" in err.getvalue()
        assert ("Traceback" in err.getvalue()) is want_trace


@pytest.mark.parametrize(
    "exc,code",
    [
        (DocumentUnreadable("x", "bad"), 4),
        (DocumentTooLarge("x", "big"), 4),
        (FileNotFoundError("x"), 4),
        (PermissionError("x"), 4),
        (ValueError("x"), 2),
        (LLMAuthError("x"), 5),
        (ImportError("x"), 5),
        (IndexUnavailable("x"), 6),
        (RuntimeError("x"), 1),
        (KeyError("x"), 1),
    ],
)
def test_exit_code_mapping(exc, code):
    assert exit_code_for(exc) == code


def test_a_console_that_cannot_encode_the_answer_does_not_crash(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore(), reply="Arrow \u2192 notation [S1]")
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    err = io.StringIO()
    code = main(
        ["ask", SEM],
        engine_factory=lambda cfg: eng,
        settings=eng.settings,
        stdout=out,
        stderr=err,
        is_tty=False,
    )
    out.flush()
    assert code == 0 and b"Arrow" in out.buffer.getvalue() and b"notation" in out.buffer.getvalue()


def test_doctor_runs_without_an_engine_and_never_prints_the_key(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore())
    cfg = dataclasses.replace(eng.settings, home=tmp_path / "fresh")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-SECRET123"}):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                ["doctor", "--json"],
                engine_factory=None,
                settings=cfg,
                stdout=out,
                stderr=err,
                is_tty=False,
            )
    rows = json.loads(out.getvalue())
    assert code in (0, 5, 6) and {r["name"] for r in rows} >= {
        "python",
        "anthropic key",
        "home",
        "index meta",
    }
    assert "SECRET123" not in out.getvalue() + err.getvalue()


def test_importing_the_cli_does_not_load_heavy_libraries():
    targets = "('torch','chromadb','sentence_transformers','anthropic')"
    code = (
        f"import sys, documind.interfaces.cli; "
        f"print(sorted(m for m in {targets} if m in sys.modules))"
    )
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert r.returncode == 0 and r.stdout.strip() == "[]", r.stdout + r.stderr


def test_stats_command(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore())
    code, out, _ = run_cli(["stats"], eng)
    assert code == 0 and "No query logs found." in out

    log_dir = eng.settings.home / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "queries.jsonl"
    rec = {
        "ts": "2026-10-09T10:00:00Z",
        "outcome": "answered",
        "total_ms": 120,
        "cost_usd": 0.0032,
    }
    log_file.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    code, out, _ = run_cli(["stats", "--json"], eng)
    assert code == 0 and json.loads(out)["query_count"] == 1
    code, out, _ = run_cli(["stats"], eng)
    assert code == 0 and "Total queries: 1" in out


def test_serve_command_loopback_and_non_loopback_warning(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore())
    cfg = dataclasses.replace(eng.settings, api_key="a" * 32)

    with patch("uvicorn.run") as mock_run:
        code, out, err = run_cli(["serve"], eng, settings=cfg)
        assert code == 0
        assert "WARNING" not in err
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 8000
        assert kwargs["workers"] == 1

    with patch("uvicorn.run") as mock_run:
        code, out, err = run_cli(
            ["serve", "--host", "0.0.0.0", "--port", "9000"],  # noqa: S104
            eng,
            settings=cfg,
        )
        assert code == 0
        assert "WARNING: Binding to non-loopback interface '0.0.0.0'" in err
        assert "TLS must be terminated" in err
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["host"] == "0.0.0.0"  # noqa: S104
        assert kwargs["port"] == 9000
        assert kwargs["workers"] == 1
