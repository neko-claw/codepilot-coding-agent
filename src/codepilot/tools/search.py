"""Repository search helpers for Sprint 1."""

import re
from pathlib import Path


def glob_search(root: str | Path, pattern: str, limit: int = 50) -> list[str]:
    """Return sorted file paths under root matching a glob pattern."""
    root_path = Path(root)
    matches = [path for path in root_path.glob(pattern) if path.is_file()]
    return sorted(str(path) for path in matches)[:limit]


def grep_search(
    root: str | Path,
    pattern: str,
    *,
    file_glob: str = "*",
    limit: int = 50,
) -> list[dict[str, str | int]]:
    """Search matching file contents and return line-numbered hits."""
    root_path = Path(root)
    regex = re.compile(pattern)
    results: list[dict[str, str | int]] = []
    for path in sorted(root_path.rglob(file_glob)):
        if not path.is_file():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if regex.search(line):
                results.append({"path": str(path), "line": line_number, "content": line})
                if len(results) >= limit:
                    return results
    return results
