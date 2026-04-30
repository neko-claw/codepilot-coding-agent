from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from codepilot.eval import BenchmarkCase
from codepilot.eval.swebench import prepare_swebench_workspace, run_swebench_case, run_swebench_suite


def _init_git_repo(repo_path: Path) -> str:
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_path, check=True)
    (repo_path / "README.md").write_text("base repo\n", encoding="utf-8")
    (repo_path / "src").mkdir()
    (repo_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md", "src/app.py"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=repo_path, check=True, capture_output=True, text=True
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_path, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_prepare_swebench_workspace_clones_git_repo_and_applies_seed_files(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    commit = _init_git_repo(repo_path)
    case = BenchmarkCase(
        name="django__django-12345",
        prompt="Fix the URL resolver bug.",
        seed_files={"notes.txt": "seeded\n"},
        metadata={"dataset": "swebench", "repo": str(repo_path), "base_commit": commit},
    )

    with prepare_swebench_workspace(case, source_repo=repo_path, checkout_ref=commit) as workspace:
        assert (workspace / "README.md").read_text(encoding="utf-8") == "base repo\n"
        assert (workspace / "src" / "app.py").read_text(encoding="utf-8") == "print('hello')\n"
        assert (workspace / "notes.txt").read_text(encoding="utf-8") == "seeded\n"
        assert (workspace / ".codepilot" / "swebench-case.json").exists()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=workspace, check=True, capture_output=True, text=True
        ).stdout.strip()
        assert head == commit


def test_run_swebench_suite_reuses_existing_case_results(tmp_path: Path, monkeypatch) -> None:
    repo_path = tmp_path / "repo"
    commit = _init_git_repo(repo_path)
    case_a = BenchmarkCase(
        name="repo-a",
        prompt="Fix repo a.",
        metadata={"dataset": "swebench", "repo": str(repo_path), "base_commit": commit},
    )
    case_b = BenchmarkCase(
        name="repo-b",
        prompt="Fix repo b.",
        metadata={"dataset": "swebench", "repo": str(repo_path), "base_commit": commit},
    )
    calls: list[BenchmarkCase] = []

    def _fake_run_swebench_case(case: BenchmarkCase, planner_client, **kwargs):
        calls.append(case)
        return SimpleNamespace(
            case=case,
            prepared_workspace=SimpleNamespace(path=tmp_path / case.name),
            session_result=SimpleNamespace(
                plan=SimpleNamespace(summary=f"summary-{case.name}", candidate_files=[]),
                inspected_files=[],
                edit_results=[],
                command_results=[],
                failure_hints=[],
            ),
        )

    def _fail_run_benchmark_case(*args, **kwargs):
        raise AssertionError("run_benchmark_case should not be called from run_swebench_suite")

    monkeypatch.setattr("codepilot.eval.swebench.run_swebench_case", _fake_run_swebench_case)
    monkeypatch.setattr("codepilot.eval.benchmark.run_benchmark_case", _fail_run_benchmark_case)

    result = run_swebench_suite([case_a, case_b], planner_client=object())

    assert [item.case.name for item in result.run_results] == ["repo-a", "repo-b"]
    assert result.benchmark_result.total == 2
    assert result.benchmark_result.passed == 2
    assert result.benchmark_result.failed == 0
    assert calls == [case_a, case_b]


def test_run_swebench_case_uses_prepared_workspace(tmp_path: Path, monkeypatch) -> None:
    repo_path = tmp_path / "repo"
    commit = _init_git_repo(repo_path)
    case = BenchmarkCase(
        name="django__django-12345",
        prompt="Fix the URL resolver bug.",
        seed_files={"notes.txt": "seeded\n"},
        command_allowlist=("pytest -q",),
        max_auto_retries=2,
        metadata={"dataset": "swebench", "repo": str(repo_path), "base_commit": commit},
    )
    calls: list[dict[str, object]] = []

    def _fake_run_task_session(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(session_id="session-1", plan=SimpleNamespace(summary="ok"))

    monkeypatch.setattr("codepilot.eval.swebench.run_task_session", _fake_run_task_session)

    result = run_swebench_case(
        case, planner_client=object(), source_repo=repo_path, checkout_ref=commit
    )

    assert result.case == case
    assert result.session_result.session_id == "session-1"
    assert len(calls) == 1
    assert Path(calls[0]["workdir"]).name == "workspace"
    workspace = Path(calls[0]["workdir"])
    assert (workspace / "README.md").exists()
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "seeded\n"
    assert calls[0]["command_allowlist"] == ("pytest -q",)
    assert calls[0]["max_auto_retries"] == 2
    assert (
        json.loads((workspace / ".codepilot" / "swebench-case.json").read_text(encoding="utf-8"))[
            "metadata"
        ]["dataset"]
        == "swebench"
    )
