from __future__ import annotations

import io
import json
from types import SimpleNamespace

from codepilot.cli import main
from codepilot.harness import (
    format_harness_json,
    format_harness_markdown,
    format_harness_text,
    format_suite_json,
    format_suite_markdown,
    format_suite_text,
)


def _fake_session_result():
    plan = SimpleNamespace(
        status="ready_to_execute",
        can_execute=True,
        next_action="execute_plan",
        summary="Build a complete harness",
        steps=("inspect", "edit", "verify"),
        candidate_files=["README.md", "src/app.py"],
        candidate_commands=["pytest -q", "ruff check ."],
        risk=SimpleNamespace(level="low", requires_confirmation=False, reason="ok"),
        user_options=["execute_plan"],
    )
    github_snapshot = SimpleNamespace(
        full_name="neko-claw/codepilot-coding-agent",
        description="CodePilot repo",
        default_branch="main",
        star_count=1,
        file_count=2,
        sample_paths=["README.md", "src/app.py"],
        readme_excerpt="# CodePilot",
        html_url="https://github.com/neko-claw/codepilot-coding-agent",
    )
    edit_result = SimpleNamespace(
        path="/repo/src/app.py",
        diff=["--- old", "+++ new"],
        syntax_check="ok",
        applied=True,
        reverted=False,
    )
    command_result = SimpleNamespace(command="pytest -q", exit_code=0, stdout="ok", stderr="")
    planner_trace = [
        SimpleNamespace(attempt_index=1, source="workspace", summary="Build", note=None)
    ]
    retry_trace = [
        SimpleNamespace(
            attempt_index=1,
            failure_type="success",
            summary="Build",
            commands=["pytest -q"],
            retried=False,
            reason="verification passed",
        )
    ]
    return SimpleNamespace(
        session_id="session-1",
        request=SimpleNamespace(
            description="Build a complete harness", workdir="/repo", mode="auto"
        ),
        plan=plan,
        local_files=["README.md", "src/app.py"],
        inspected_files=["README.md"],
        github_snapshot=github_snapshot,
        edit_results=[edit_result],
        command_results=[command_result],
        planner_trace=planner_trace,
        retry_trace=retry_trace,
        failure_hints=["none"],
        rollback_snapshot_id="snapshot-1",
    )


def test_harness_text_markdown_and_json_reports_are_serializable() -> None:
    result = _fake_session_result()

    text = format_harness_text(result)
    markdown = format_harness_markdown(result)
    data = json.loads(format_harness_json(result))

    assert "CodePilot Harness Report" in text
    assert "session_id: session-1" in text
    assert "Build a complete harness" in text
    assert "## Candidate Files" in markdown
    assert data["session_id"] == "session-1"
    assert data["plan"]["summary"] == "Build a complete harness"
    assert data["edit_results"][0]["applied"] is True
    assert data["command_results"][0]["exit_code"] == 0


def test_harness_suite_serialization_formats_text_markdown_json() -> None:
    case = SimpleNamespace(
        name="agent_bootstrap",
        prompt="Create an agent",
        mode="auto",
        seed_files={"README.md": "# Demo\n"},
        command_allowlist=("pytest -q",),
        max_auto_retries=1,
        expected_candidate_files=("src/agent.py",),
        expected_inspected_files=("README.md",),
        expected_written_files=("src/agent.py",),
        expected_written_file_contains={"src/agent.py": "class Agent"},
        expected_command_exit_codes={"pytest -q": 0},
        expected_summary_contains=("agent",),
        expected_file_reads=("README.md",),
        metadata={"dataset": "fixture"},
    )
    case_result = SimpleNamespace(case=case, passed=True, observations=["ok"], failures=[])
    benchmark_result = SimpleNamespace(total=1, passed=1, failed=0, case_results=[case_result])

    text = format_suite_text(benchmark_result)
    markdown = format_suite_markdown(benchmark_result)
    data = json.loads(format_suite_json(benchmark_result))

    assert "CodePilot Harness Benchmark Report" in text
    assert "passed=True" in text
    assert "## Cases" in markdown
    assert data["total"] == 1
    assert data["cases"][0]["name"] == "agent_bootstrap"


def test_main_harness_run_and_eval_routes(monkeypatch, tmp_path) -> None:
    run_calls: list[dict[str, object]] = []
    eval_calls: list[dict[str, object]] = []

    def _fake_load_config(workdir):
        return SimpleNamespace(
            storage_dir=tmp_path / ".codepilot",
            deepseek_enabled=False,
            deepseek_api_key=None,
            deepseek_base_url="https://api.deepseek.com/v1",
            deepseek_model="deepseek-chat",
            deepseek_timeout=15.0,
        )

    monkeypatch.setattr("codepilot.cli.load_config", _fake_load_config)
    monkeypatch.setattr(
        "codepilot.cli.run_harness_session",
        lambda **kwargs: run_calls.append(kwargs) or _fake_session_result(),
    )
    monkeypatch.setattr(
        "codepilot.cli.run_harness_suite",
        lambda *args, **kwargs: (
            eval_calls.append({"args": args, "kwargs": kwargs})
            or SimpleNamespace(total=1, passed=1, failed=0, case_results=[])
        ),
    )
    monkeypatch.setattr("codepilot.cli._build_planner_client", lambda config: object())

    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    exit_code = main(
        [
            "harness",
            "run",
            "Build a complete harness",
            "--workdir",
            str(tmp_path),
            "--format",
            "json",
            "--command-allowlist",
            "pytest -q",
        ]
    )

    assert exit_code == 0
    assert run_calls[0]["description"] == "Build a complete harness"
    assert run_calls[0]["mode"] == "auto"
    assert run_calls[0]["command_allowlist"] == ("pytest -q",)
    assert json.loads(out.getvalue().strip())["session_id"] == "session-1"

    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    exit_code = main(
        [
            "harness",
            "eval",
            "suite.json",
            "--workdir",
            str(tmp_path),
            "--dataset-format",
            "auto",
            "--format",
            "text",
        ]
    )

    assert exit_code == 0
    assert eval_calls[0]["args"] == ("suite.json",)
    assert eval_calls[0]["kwargs"]["dataset_format"] == "auto"
    assert "CodePilot Harness Benchmark Report" in out.getvalue()
