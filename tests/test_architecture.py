import ast
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "documind" / "core"
FORBIDDEN = {
    "fastapi",
    "starlette",
    "uvicorn",
    "mcp",
    "argparse",
    "typer",
    "click",
    "documind.interfaces",
}


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_core_never_imports_an_interface() -> None:
    offenders: dict[str, list[str]] = {}
    for f in CORE.rglob("*.py"):
        bad = {i for i in _imports(f) if any(i == b or i.startswith(b + ".") for b in FORBIDDEN)}
        if bad:
            offenders[f.name] = sorted(bad)
    assert not offenders, offenders
