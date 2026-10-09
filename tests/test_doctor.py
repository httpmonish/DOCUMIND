"""tests/test_doctor.py -- pure installation checks (documind/core/doctor.py satisfies this)."""

from __future__ import annotations

import json

import pytest

from documind.core.doctor import (
    Check,
    check_api_key,
    check_extras,
    check_home,
    check_meta,
    check_python,
    exit_code,
)


def test_python_version():
    assert check_python((3, 9, 18)).status == "fail"
    assert check_python((3, 10, 0)).status == "ok" and check_python((3, 12, 3)).status == "ok"


def test_api_key_is_reported_as_set_or_missing_and_never_echoed():
    assert check_api_key({}).status == "warn"
    assert check_api_key({"ANTHROPIC_API_KEY": "   "}).status == "warn"
    c = check_api_key({"ANTHROPIC_API_KEY": "sk-ant-SECRET123"})
    assert c.status == "ok" and "SECRET123" not in c.detail and "SECRET123" not in repr(c)


def test_home_directory(tmp_path):
    assert check_home(tmp_path / "missing").status == "warn"
    assert check_home(tmp_path).status == "ok"
    f = tmp_path / "afile"
    f.write_text("x")
    c = check_home(f)
    assert c.status == "fail" and c.category == "index"


def test_meta_consistency(tmp_path):
    assert check_meta(tmp_path, "m", 1).status == "warn"  # no index yet
    (tmp_path / "meta.json").write_text("{not json", encoding="utf-8")
    assert check_meta(tmp_path, "m", 1).status == "fail"
    (tmp_path / "meta.json").write_text(
        json.dumps({"embed_model": "old-model", "schema_version": 1}), encoding="utf-8"
    )
    c = check_meta(tmp_path, "new-model", 1)
    assert (
        c.status == "fail"
        and "old-model" in c.detail
        and "new-model" in c.detail
        and c.category == "index"
    )
    (tmp_path / "meta.json").write_text(
        json.dumps({"embed_model": "m", "schema_version": 1}), encoding="utf-8"
    )
    assert check_meta(tmp_path, "m", 1).status == "ok"
    assert check_meta(tmp_path, "m", 2).status == "fail"  # schema bump


def test_missing_extras_say_how_to_fix_it():
    checks = check_extras(lambda name: None if name == "sentence_transformers" else object())
    by = {c.name: c for c in checks}
    assert by["embedder"].status == "fail" and "documind[embed]" in by["embedder"].detail
    assert by["vector store"].status == "ok" and by["llm client"].status == "ok"


@pytest.mark.parametrize(
    "checks,code",
    [
        ([Check("a", "ok", ""), Check("b", "warn", "")], 0),
        ([Check("a", "fail", "", "config")], 5),
        ([Check("a", "fail", "", "index")], 6),
        ([Check("a", "fail", "", "config"), Check("b", "fail", "", "index")], 6),
        ([], 0),
    ],
)
def test_exit_codes(checks, code):
    assert exit_code(checks) == code
