"""Text input and output must name its encoding and newline so results are identical on Linux and Windows.

The default encoding on Windows is not UTF-8 and text mode writes CRLF line endings. This check parses the source with
`ast` and fails for any call that would fall back on the platform defaults.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = [ROOT / "src" / "tashwish", ROOT / "scripts"]

# Modules that are not yet covered by this check. Remove an entry once the module passes.
PENDING = {
    "src/tashwish/validate/run.py",
}

NOT_TEXT_FILES = {"tarfile", "gzip", "io", "os", "webbrowser"}


def _kw(call: ast.Call) -> set[str]:
    return {k.arg for k in call.keywords if k.arg}


def _mode(call: ast.Call, position: int) -> str | None:
    node = None
    if len(call.args) > position:
        node = call.args[position]
    for k in call.keywords:
        if k.arg == "mode":
            node = k.value
    if node is None:
        return "r"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None  # not a literal, cannot judge


def problems(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kw = _kw(node)
        f = node.func
        where = f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
        is_builtin_open = isinstance(f, ast.Name) and f.id == "open"
        is_path_open = isinstance(f, ast.Attribute) and f.attr == "open"
        if is_path_open and isinstance(f.value, ast.Name) and f.value.id in NOT_TEXT_FILES:
            continue
        if is_builtin_open or is_path_open:
            mode = _mode(node, 1 if is_builtin_open else 0)
            if mode is None or "b" in mode:
                continue
            if "encoding" not in kw:
                out.append(f"{where}: open() in text mode without encoding")
            if any(c in mode for c in "wax+") and "newline" not in kw:
                out.append(f"{where}: open() for writing without newline")
            continue
        if isinstance(f, ast.Attribute):
            if f.attr == "read_text" and "encoding" not in kw:
                out.append(f"{where}: read_text() without encoding")
            elif f.attr == "write_text":
                if "encoding" not in kw:
                    out.append(f"{where}: write_text() without encoding")
                if "newline" not in kw:
                    out.append(f"{where}: write_text() without newline")
            elif f.attr == "to_csv" and "lineterminator" not in kw:
                out.append(f"{where}: to_csv() without lineterminator")
            elif (
                f.attr == "run"
                and isinstance(f.value, ast.Name)
                and f.value.id == "subprocess"
                and ("text" in kw or "universal_newlines" in kw)
                and "encoding" not in kw
            ):
                out.append(f"{where}: subprocess text mode without encoding")
    return out


def _files() -> list[Path]:
    files = []
    for base in SCAN:
        files += sorted(base.rglob("*.py"))
    return [p for p in files if p.relative_to(ROOT).as_posix() not in PENDING]


def test_files_were_found():
    assert len(_files()) > 30


def test_text_io_names_encoding_and_newline():
    found = [msg for p in _files() for msg in problems(p)]
    assert not found, "\n".join(found)


def test_checker_flags_a_bad_call(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text(
        "from pathlib import Path\n"
        "Path('a').read_text()\n"
        "Path('a').write_text('x')\n"
        "open('a', 'w')\n"
        "open('a', 'rb')\n"
        "df.to_csv('a')\n",
        encoding="utf-8",
        newline="\n",
    )
    tree_root = bad.parent
    assert tree_root == tmp_path
    msgs = _check_outside_root(bad)
    assert len(msgs) == 6


def _check_outside_root(path: Path) -> list[str]:
    global ROOT
    saved = ROOT
    ROOT = path.parent
    try:
        return problems(path)
    finally:
        ROOT = saved
