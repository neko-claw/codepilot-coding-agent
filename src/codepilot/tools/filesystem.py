"""File reading, writing, and editing helpers for CodePilot."""

import difflib
import py_compile
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileReadResult:
    """Line-numbered file content."""

    content: list[str]
    total_lines: int


@dataclass(frozen=True, slots=True)
class FileEditResult:
    """Outcome of an old-string-to-new-string file edit."""

    updated_text: str
    diff: list[str]
    syntax_check: str
    applied: bool = True
    reverted: bool = False


def read_file_with_line_numbers(
    path: str | Path,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
) -> FileReadResult:
    """Read a file and optionally slice by line numbers."""
    target = Path(path)
    lines = target.read_text(encoding="utf-8").splitlines()
    total_lines = len(lines)
    start = 1 if start_line is None else start_line
    end = total_lines if end_line is None else end_line
    if start < 1 or end < start:
        raise ValueError("start_line must be >= 1 and <= end_line")
    selected = lines[start - 1 : end]
    numbered = [f"{line_no}|{line}" for line_no, line in enumerate(selected, start=start)]
    return FileReadResult(content=numbered, total_lines=total_lines)


def edit_file_by_replacement(
    path: str | Path,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
    restore_on_syntax_error: bool = False,
) -> FileEditResult:
    """Replace text deterministically and return diff plus syntax status."""
    target = Path(path)
    original_text = target.read_text(encoding="utf-8")
    occurrences = original_text.count(old_string)
    if occurrences == 0:
        raise ValueError("old string not found")
    if occurrences > 1 and not replace_all:
        raise ValueError("old string appears multiple times")
    updated_text = original_text.replace(old_string, new_string, -1 if replace_all else 1)
    diff = list(
        difflib.unified_diff(
            original_text.splitlines(),
            updated_text.splitlines(),
            fromfile=str(target),
            tofile=str(target),
            lineterm="",
        )
    )
    target.write_text(updated_text, encoding="utf-8")
    _clear_python_bytecode_cache(target)
    syntax_check = _python_syntax_check(target)
    if restore_on_syntax_error and syntax_check.startswith("error:"):
        target.write_text(original_text, encoding="utf-8")
        _clear_python_bytecode_cache(target)
        return FileEditResult(
            updated_text=original_text,
            diff=diff,
            syntax_check=syntax_check,
            applied=False,
            reverted=True,
        )
    return FileEditResult(
        updated_text=updated_text,
        diff=diff,
        syntax_check=syntax_check,
        applied=True,
        reverted=False,
    )


def write_file_contents(
    path: str | Path,
    content: str,
    *,
    create_parents: bool = True,
    restore_on_syntax_error: bool = False,
) -> FileEditResult:
    """Create or fully rewrite a file and return diff plus syntax status."""
    target = Path(path)
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    original_text = target.read_text(encoding="utf-8") if existed else ""
    diff = list(
        difflib.unified_diff(
            original_text.splitlines(),
            content.splitlines(),
            fromfile=str(target),
            tofile=str(target),
            lineterm="",
        )
    )
    target.write_text(content, encoding="utf-8")
    _clear_python_bytecode_cache(target)
    syntax_check = _python_syntax_check(target)
    if restore_on_syntax_error and syntax_check.startswith("error:"):
        if existed:
            target.write_text(original_text, encoding="utf-8")
        else:
            target.unlink(missing_ok=True)
        _clear_python_bytecode_cache(target)
        return FileEditResult(
            updated_text=original_text,
            diff=diff,
            syntax_check=syntax_check,
            applied=False,
            reverted=True,
        )
    return FileEditResult(
        updated_text=content,
        diff=diff,
        syntax_check=syntax_check,
        applied=True,
        reverted=False,
    )


def _clear_python_bytecode_cache(path: Path) -> None:
    if path.suffix != ".py":
        return
    pycache_dir = path.parent / "__pycache__"
    if not pycache_dir.exists():
        return
    stem = path.stem
    for compiled in pycache_dir.glob(f"{stem}*.pyc"):
        compiled.unlink(missing_ok=True)


def _python_syntax_check(path: Path) -> str:
    if path.suffix != ".py":
        return "skipped"
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    try:
        temp_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        py_compile.compile(str(temp_path), doraise=True)
    except py_compile.PyCompileError as exc:
        return f"error: {exc.msg}"
    finally:
        temp_path.unlink(missing_ok=True)
    return "ok"
