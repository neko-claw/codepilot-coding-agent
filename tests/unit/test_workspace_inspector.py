from pathlib import Path

from codepilot.workspace.inspector import inspect_workspace


def test_inspect_workspace_detects_python_repo_commands_and_candidate_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff]\nline-length = 100\n",
        encoding="utf-8",
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tests_dir / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    profile = inspect_workspace(tmp_path, "修复失败测试并检查质量门禁")

    assert "Python" in profile.summary
    assert any(path.endswith("README.md") for path in profile.candidate_files)
    assert any(path.endswith("tests/test_app.py") for path in profile.candidate_files)
    assert "pytest -q" in profile.candidate_commands
    assert "ruff check ." in profile.candidate_commands


def test_inspect_workspace_prioritizes_docs_for_planning_tasks(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")

    profile = inspect_workspace(tmp_path, "为当前仓库制定重构计划并更新文档")

    assert profile.candidate_files[0].endswith("README.md")
    assert any(path.endswith("docs/architecture.md") for path in profile.candidate_files[:4])


def test_inspect_workspace_bootstraps_empty_agent_repo(tmp_path: Path) -> None:
    profile = inspect_workspace(tmp_path, "从零创建一个可用的 coding agent")

    assert "bootstrap" in profile.summary.lower()
    assert any(path.endswith("src/agent.py") for path in profile.candidate_files)
    assert any(path.endswith("src/cli.py") for path in profile.candidate_files)
    assert any(path.endswith("tests/test_agent.py") for path in profile.candidate_files)
