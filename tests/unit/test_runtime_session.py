from __future__ import annotations

from pathlib import Path

from codepilot.integrations.github import GitHubRepoRef, GitHubRepoSnapshot
from codepilot.runtime.session import run_task_session


class _FakeGitHubClient:
    def fetch_snapshot(self, repo_ref: GitHubRepoRef) -> GitHubRepoSnapshot:
        return GitHubRepoSnapshot(
            full_name=f"{repo_ref.owner}/{repo_ref.name}",
            description="demo",
            default_branch="main",
            star_count=1,
            file_count=2,
            sample_paths=["README.md", "src/app.py"],
            readme_excerpt="Demo README",
            html_url="https://github.com/octo/demo",
        )


def test_run_task_session_plan_mode_collects_local_and_github_context(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hello')\n", encoding="utf-8")

    result = run_task_session(
        description="为项目补充测试计划",
        workdir=tmp_path,
        mode="plan",
        github_repo=GitHubRepoRef(owner="octo", name="demo"),
        github_client=_FakeGitHubClient(),
    )

    assert result.plan.status == "awaiting_confirmation"
    assert result.github_snapshot is not None
    assert result.github_snapshot.full_name == "octo/demo"
    assert any(path.endswith("README.md") for path in result.local_files)
    assert result.command_results == []


def test_run_task_session_auto_mode_executes_candidate_commands(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text(
        "def test_demo():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    result = run_task_session(
        description="验证当前仓库测试是否通过",
        workdir=tmp_path,
        mode="auto",
        command_allowlist=("pytest -q",),
    )

    assert result.plan.status == "ready_to_execute"
    assert len(result.command_results) == 1
    assert result.command_results[0].command == "pytest -q"
    assert result.command_results[0].exit_code == 0
