"""Workspace inspection helpers for realistic planning and command suggestions."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkspaceProfile:
    """Summarized repository context used for planning."""

    summary: str
    candidate_files: list[str]
    candidate_commands: list[str]


def inspect_workspace(
    workdir: str | Path,
    task_description: str,
    *,
    max_candidate_files: int = 8,
) -> WorkspaceProfile:
    """Inspect a repository and suggest relevant files plus safe candidate commands."""
    root = Path(workdir).resolve()
    candidate_files = _collect_candidate_files(root, task_description, max_candidate_files)
    bootstrap_used = False
    if not candidate_files:
        candidate_files = _bootstrap_candidate_files(root, task_description, max_candidate_files)
        bootstrap_used = True
    candidate_commands = _detect_candidate_commands(root)
    summary = _build_summary(
        root, candidate_files, candidate_commands, bootstrap_used=bootstrap_used
    )
    return WorkspaceProfile(
        summary=summary,
        candidate_files=candidate_files,
        candidate_commands=candidate_commands,
    )


def _collect_candidate_files(root: Path, task_description: str, limit: int) -> list[str]:
    description = task_description.lower()
    scored_paths: dict[Path, int] = {}

    def _add_matches(pattern: str, base_score: int) -> None:
        for path in root.glob(pattern):
            if path.is_file():
                resolved = path.resolve()
                scored_paths[resolved] = max(scored_paths.get(resolved, 0), base_score)

    _add_matches("README*", 100)
    _add_matches("pyproject.toml", 92)
    _add_matches("package.json", 92)
    _add_matches("docs/**/*.md", 78)
    _add_matches("src/**/*.py", 72)
    _add_matches("app/**/*.py", 70)
    _add_matches("tests/**/*.py", 68)

    if any(keyword in description for keyword in ("test", "测试", "失败", "质量", "lint")):
        _boost_matches(scored_paths, root.glob("tests/**/*.py"), 25)
        _boost_matches(scored_paths, root.glob("pyproject.toml"), 20)
    if any(keyword in description for keyword in ("plan", "规划", "方案", "文档", "重构", "设计")):
        _boost_matches(scored_paths, root.glob("README*"), 18)
        _boost_matches(scored_paths, root.glob("docs/**/*.md"), 22)
    if any(keyword in description for keyword in ("build", "构建", "依赖", "release", "发布")):
        _boost_matches(scored_paths, root.glob("pyproject.toml"), 24)
        _boost_matches(scored_paths, root.glob("package.json"), 24)

    ranked = sorted(
        scored_paths.items(),
        key=lambda item: (-item[1], item[0].as_posix()),
    )
    return [str(path) for path, _score in ranked[:limit]]


def _bootstrap_candidate_files(root: Path, task_description: str, limit: int) -> list[str]:
    description = task_description.lower()
    bootstrap_targets = _bootstrap_targets_for_description(root, description)
    return [str(path) for path in bootstrap_targets[:limit]]


def _bootstrap_targets_for_description(root: Path, description: str) -> list[Path]:
    if any(
        keyword in description
        for keyword in ("agent", "coding agent", "assistant", "代理", "智能体")
    ):
        return [
            root / "README.md",
            root / "pyproject.toml",
            root / "src" / "agent.py",
            root / "src" / "cli.py",
            root / "tests" / "test_agent.py",
            root / "src" / "__init__.py",
        ]
    if any(
        keyword in description for keyword in ("javascript", "typescript", "node", "npm", "前端")
    ):
        return [
            root / "README.md",
            root / "package.json",
            root / "src" / "index.ts",
            root / "tests" / "test_app.ts",
        ]
    return [
        root / "README.md",
        root / "pyproject.toml",
        root / "src" / "app.py",
        root / "tests" / "test_app.py",
        root / "src" / "__init__.py",
    ]


def _boost_matches(scored_paths: dict[Path, int], paths, amount: int) -> None:
    for path in paths:
        if path.is_file():
            resolved = path.resolve()
            scored_paths[resolved] = scored_paths.get(resolved, 0) + amount


def _detect_candidate_commands(root: Path) -> list[str]:
    commands: list[str] = []
    pyproject_path = root / "pyproject.toml"
    package_json_path = root / "package.json"

    if pyproject_path.exists() or any(root.glob("tests/**/*.py")):
        commands.append("pytest -q")
    if _ruff_is_configured(pyproject_path, root):
        commands.append("ruff check .")
    if package_json_path.exists():
        commands.extend(_npm_candidate_commands(package_json_path))

    return list(dict.fromkeys(commands)) or ["pytest -q", "ruff check ."]


def _ruff_is_configured(pyproject_path: Path, root: Path) -> bool:
    if (root / ".ruff.toml").exists() or (root / "ruff.toml").exists():
        return True
    if not pyproject_path.exists():
        return any(root.glob("**/*.py"))
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return True
    tool_section = payload.get("tool", {})
    return "ruff" in tool_section or any(root.glob("**/*.py"))


def _npm_candidate_commands(package_json_path: Path) -> list[str]:
    try:
        payload = json.loads(package_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["npm test"]
    scripts = payload.get("scripts", {})
    commands: list[str] = []
    if "test" in scripts:
        commands.append("npm test")
    if "lint" in scripts:
        commands.append("npm run lint")
    if "build" in scripts:
        commands.append("npm run build")
    return commands or ["npm test"]


def _build_summary(
    root: Path,
    candidate_files: list[str],
    candidate_commands: list[str],
    *,
    bootstrap_used: bool,
) -> str:
    detected_stack = _detect_stack(root)
    file_preview = ", ".join(Path(path).name for path in candidate_files[:3]) or "no key files"
    command_preview = ", ".join(candidate_commands[:3]) or "no candidate commands"
    bootstrap_note = " Bootstrap scaffold suggested." if bootstrap_used else ""
    return (
        f"Detected {detected_stack} workspace at {root}. "
        f"Key files: {file_preview}. Candidate commands: {command_preview}."
        f"{bootstrap_note}"
    )


def _detect_stack(root: Path) -> str:
    if (root / "pyproject.toml").exists() or any(root.glob("**/*.py")):
        return "Python"
    if (root / "package.json").exists():
        return "JavaScript/TypeScript"
    return "generic"
