from __future__ import annotations

import io
import json
from types import SimpleNamespace

from codepilot.cli import main
from codepilot.harness import (
    format_harness_json,
    format_harness_markdown,
    format_harness_text,
    format_loop_json,
    format_loop_markdown,
    format_loop_text,
    format_suite_json,
    format_suite_markdown,
    format_suite_text,
    resume_harness_session,
    run_harness_loop,
)


def _fake_session_result(execution_budget=None):
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
        execution_budget=execution_budget,
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
    monkeypatch.setattr(
        "codepilot.cli.resume_harness_session",
        lambda *args, **kwargs: (
            run_calls.append({"resume_args": args, "resume_kwargs": kwargs})
            or _fake_session_result()
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

    (tmp_path / ".codepilot" / "history").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".codepilot" / "history" / "session-42.json").write_text(
        json.dumps(
            {
                "session_id": "session-42",
                "description": "Resume the last harness run",
                "mode": "auto",
                "status": "done",
                "workdir": str(tmp_path),
                "created_at": "2026-01-01T00:00:00Z",
                "risk_level": "low",
                "commands": ["pytest -q", "ruff check ."],
            }
        ),
        encoding="utf-8",
    )

    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    exit_code = main(
        [
            "harness",
            "resume",
            "session-42",
            "--format",
            "text",
        ]
    )

    assert exit_code == 0
    assert run_calls[-1]["resume_args"] == ("session-42",)
    assert run_calls[-1]["resume_kwargs"]["storage_dir"] == tmp_path / ".codepilot"
    assert run_calls[-1]["resume_kwargs"]["mode"] is None
    assert run_calls[-1]["resume_kwargs"]["max_auto_retries"] == 1
    assert run_calls[-1]["resume_kwargs"]["strict_command_allowlist"] is False
    assert "CodePilot Harness Report" in out.getvalue()


def test_resume_harness_session_replays_saved_metadata(monkeypatch, tmp_path) -> None:
    storage_dir = tmp_path / ".codepilot"
    history_dir = storage_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "session-42.json").write_text(
        json.dumps(
            {
                "session_id": "session-42",
                "description": "Resume the last harness run",
                "mode": "auto",
                "status": "done",
                "workdir": str(tmp_path),
                "created_at": "2026-01-01T00:00:00Z",
                "risk_level": "low",
                "commands": ["pytest -q", "ruff check ."],
            }
        ),
        encoding="utf-8",
    )

    calls: dict[str, object] = {}
    monkeypatch.setattr(
        "codepilot.harness.runner.run_harness_session",
        lambda **kwargs: calls.update(kwargs) or _fake_session_result(),
    )

    result = resume_harness_session(
        "session-42",
        storage_dir=storage_dir,
        planner_client=object(),
        mode="auto",
        max_auto_retries=3,
        strict_command_allowlist=True,
    )

    assert result.session_id == "session-1"
    assert calls["description"] == "Resume the last harness run"
    assert calls["workdir"] == str(tmp_path)
    assert calls["mode"] == "auto"
    assert calls["command_allowlist"] == ("pytest -q", "ruff check .")
    assert calls["max_auto_retries"] == 3
    assert calls["strict_command_allowlist"] is True


def test_harness_loop_serialization_and_formatting() -> None:
    loop_result = SimpleNamespace(
        description="Fix the failing task",
        workdir="/repo",
        completed=True,
        stop_reason="success",
        rounds=[
            SimpleNamespace(
                round_index=1,
                success=False,
                reason="assertion failed in tests/test_demo.py",
                session_result=_fake_session_result(),
            ),
            SimpleNamespace(
                round_index=2,
                success=True,
                reason="verification passed",
                session_result=_fake_session_result(),
            ),
        ],
    )

    text = format_loop_text(loop_result)
    markdown = format_loop_markdown(loop_result)
    data = json.loads(format_loop_json(loop_result))

    assert "CodePilot Harness Loop Report" in text
    assert "stop_reason: success" in text
    assert "## Rounds" in markdown
    assert data["completed"] is True
    assert data["rounds"][0]["reason"] == "assertion failed in tests/test_demo.py"


def test_harness_reports_execution_budget() -> None:
    execution_budget = SimpleNamespace(
        command_limit=1,
        command_used=1,
        command_exhausted=True,
        edit_limit=2,
        edit_used=1,
        edit_exhausted=False,
        stop_reason="command budget exhausted",
    )
    result = _fake_session_result(execution_budget=execution_budget)

    text = format_harness_text(result)
    markdown = format_harness_markdown(result)
    data = json.loads(format_harness_json(result))

    assert "execution_budget:" in text
    assert "command_used=1 limit=1 exhausted=True" in text
    assert "## Execution Budget" in markdown
    assert data["execution_budget"]["stop_reason"] == "command budget exhausted"


def test_run_harness_loop_retries_with_failure_context_until_success(monkeypatch, tmp_path) -> None:
    results = [
        SimpleNamespace(
            session_id="round-1",
            request=SimpleNamespace(
                description="Fix the failing task", workdir=str(tmp_path), mode="auto"
            ),
            plan=SimpleNamespace(
                status="ready_to_execute",
                can_execute=True,
                next_action="execute_plan",
                summary="Round 1",
                steps=("inspect", "run tests"),
                candidate_files=["README.md"],
                candidate_commands=["pytest -q"],
                risk=SimpleNamespace(level="low", requires_confirmation=False, reason="ok"),
                user_options=["execute_plan"],
            ),
            local_files=["README.md"],
            inspected_files=["README.md"],
            github_snapshot=None,
            edit_results=[],
            command_results=[
                SimpleNamespace(command="pytest -q", exit_code=1, stdout="fail", stderr="boom")
            ],
            planner_trace=[],
            retry_trace=[],
            failure_hints=["assertion failed in tests/test_demo.py"],
            rollback_snapshot_id="snapshot-1",
        ),
        SimpleNamespace(
            session_id="round-2",
            request=SimpleNamespace(
                description="Fix the failing task", workdir=str(tmp_path), mode="auto"
            ),
            plan=SimpleNamespace(
                status="ready_to_execute",
                can_execute=True,
                next_action="execute_plan",
                summary="Round 2",
                steps=("inspect", "run tests"),
                candidate_files=["README.md"],
                candidate_commands=["pytest -q"],
                risk=SimpleNamespace(level="low", requires_confirmation=False, reason="ok"),
                user_options=["execute_plan"],
            ),
            local_files=["README.md"],
            inspected_files=["README.md"],
            github_snapshot=None,
            edit_results=[],
            command_results=[
                SimpleNamespace(command="pytest -q", exit_code=0, stdout="ok", stderr="")
            ],
            planner_trace=[],
            retry_trace=[],
            failure_hints=[],
            rollback_snapshot_id="snapshot-2",
        ),
    ]
    calls: list[dict[str, object]] = []

    def _fake_run_harness_session(**kwargs):
        calls.append(kwargs)
        return results[len(calls) - 1]

    monkeypatch.setattr("codepilot.harness.runner.run_harness_session", _fake_run_harness_session)

    result = run_harness_loop(
        description="Fix the failing task",
        workdir=tmp_path,
        planner_client=object(),
        max_rounds=3,
    )

    assert result.completed is True
    assert result.rounds[0].session_result.session_id == "round-1"
    assert result.rounds[1].session_result.session_id == "round-2"
    assert result.rounds[0].success is False
    assert result.rounds[1].success is True
    assert len(calls) == 2
    assert "assertion failed in tests/test_demo.py" in calls[1]["description"]
    assert result.stop_reason == "success"


def test_run_harness_loop_marks_budget_exhaustion_as_failure(monkeypatch, tmp_path) -> None:
    execution_budget = SimpleNamespace(
        command_limit=1,
        command_used=1,
        command_exhausted=True,
        edit_limit=None,
        edit_used=0,
        edit_exhausted=False,
        stop_reason="command budget exhausted",
    )
    budget_result = _fake_session_result(execution_budget=execution_budget)
    success_result = _fake_session_result()
    calls: list[dict[str, object]] = []

    def _fake_run_harness_session(**kwargs):
        calls.append(kwargs)
        return budget_result if len(calls) == 1 else success_result

    monkeypatch.setattr("codepilot.harness.runner.run_harness_session", _fake_run_harness_session)

    result = run_harness_loop(
        description="Fix the failing task",
        workdir=tmp_path,
        planner_client=object(),
        max_rounds=2,
    )

    assert result.rounds[0].success is False
    assert result.rounds[0].reason == "command budget exhausted"
    assert "command budget exhausted" in calls[1]["description"]
    assert result.completed is True
    assert result.stop_reason == "success"


def test_run_harness_loop_includes_target_files_in_retry_context(monkeypatch, tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "tests" / "test_demo.py").write_text("assert True\n", encoding="utf-8")
    first_result = SimpleNamespace(
        session_id="round-1",
        request=SimpleNamespace(
            description="Fix the failing task", workdir=str(tmp_path), mode="auto"
        ),
        plan=SimpleNamespace(
            status="ready_to_execute",
            can_execute=True,
            next_action="execute_plan",
            summary="Round 1",
            steps=("inspect", "run tests"),
            candidate_files=["README.md"],
            candidate_commands=["pytest -q"],
            risk=SimpleNamespace(level="low", requires_confirmation=False, reason="ok"),
            user_options=["execute_plan"],
        ),
        local_files=["README.md"],
        inspected_files=["README.md"],
        github_snapshot=None,
        edit_results=[SimpleNamespace(path=str(tmp_path / "src" / "app.py"), applied=False, reverted=False, syntax_check="error: invalid syntax")],
        command_results=[
            SimpleNamespace(
                command=f"pytest -q {tmp_path / 'tests' / 'test_demo.py'}",
                exit_code=1,
                stdout="fail",
                stderr=f"Traceback in {tmp_path / 'tests' / 'test_demo.py'}",
            )
        ],
        planner_trace=[],
        retry_trace=[],
        failure_hints=["assertion failed in tests/test_demo.py"],
        rollback_snapshot_id="snapshot-1",
    )
    second_result = _fake_session_result()
    calls: list[dict[str, object]] = []

    def _fake_run_harness_session(**kwargs):
        calls.append(kwargs)
        return first_result if len(calls) == 1 else second_result

    monkeypatch.setattr("codepilot.harness.runner.run_harness_session", _fake_run_harness_session)

    result = run_harness_loop(
        description="Fix the failing task",
        workdir=tmp_path,
        planner_client=object(),
        max_rounds=2,
    )

    assert result.completed is True
    assert "target files:" in calls[1]["description"]
    assert "src/app.py" in calls[1]["description"]
    assert "tests/test_demo.py" in calls[1]["description"]
    assert result.rounds[0].success is False
    assert result.rounds[1].success is True


def test_main_harness_loop_route(monkeypatch, tmp_path) -> None:
    loop_calls: list[dict[str, object]] = []

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
        "codepilot.cli.run_harness_loop",
        lambda **kwargs: (
            loop_calls.append(kwargs)
            or SimpleNamespace(
                description=kwargs["description"],
                workdir=str(kwargs["workdir"]),
                completed=True,
                stop_reason="success",
                rounds=[],
            )
        ),
    )

    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    exit_code = main(
        [
            "harness",
            "loop",
            "Refine the failing task until tests pass",
            "--workdir",
            str(tmp_path),
            "--max-rounds",
            "2",
            "--max-commands",
            "4",
            "--max-edits",
            "3",
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    assert loop_calls[0]["description"] == "Refine the failing task until tests pass"
    assert loop_calls[0]["max_rounds"] == 2
    assert loop_calls[0]["max_command_results"] == 4
    assert loop_calls[0]["max_edit_results"] == 3
    assert json.loads(out.getvalue().strip())["completed"] is True
