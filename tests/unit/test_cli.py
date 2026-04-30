import io
from pathlib import Path
from types import SimpleNamespace

from codepilot.cli import (
    InteractiveShellState,
    build_completion_candidates,
    configure_shell_readline,
    main,
    render_shell_intro,
    run_interactive_shell,
)
from codepilot.integrations.deepseek import FileEditSuggestion, PlannerSuggestion
from codepilot.storage.session_store import SessionRecord, SessionStore
from codepilot.ui.tui import render_tui_snapshot


class _FakeSessionResult:
    def __init__(self, *, mode: str = "plan") -> None:
        status = "awaiting_confirmation" if mode == "plan" else "ready_to_execute"
        next_action = "wait_for_user_confirmation" if mode == "plan" else "execute_plan"
        user_options = (
            ["continue_discussing_plan", "confirm_execution", "cancel_task"]
            if mode == "plan"
            else ["execute_plan"]
        )
        self.plan = type(
            "Plan",
            (),
            {
                "status": status,
                "can_execute": mode != "plan",
                "next_action": next_action,
                "summary": f"generated {mode} plan",
                "steps": ("Read files", "Run tests"),
                "candidate_files": ["README.md", "tests/test_demo.py"],
                "candidate_commands": ["pytest -q"],
                "risk": type("Risk", (), {"level": "low", "reason": "safe"})(),
                "user_options": user_options,
            },
        )()
        self.request = type("Request", (), {"workdir": "/tmp/demo"})()
        self.github_snapshot = None
        self.inspected_files = ["README.md"]
        self.edit_results = [
            type(
                "EditResult",
                (),
                {
                    "path": "src/app.py",
                    "applied": mode != "plan",
                    "reverted": False,
                    "syntax_check": "ok",
                    "diff": ["--- a/src/app.py", "+++ b/src/app.py", "+return 42"],
                },
            )()
        ]
        self.command_results = [
            type(
                "CommandResult",
                (),
                {
                    "command": "pytest -q",
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": f"Traceback in {Path('/tmp/demo/src/app.py')}",
                },
            )()
        ]
        self.planner_trace = [
            type(
                "PlannerTrace",
                (),
                {
                    "attempt_index": 1,
                    "source": "deepseek",
                    "summary": f"generated {mode} plan",
                    "note": None,
                },
            )()
        ]
        self.retry_trace = [
            type(
                "RetryTrace",
                (),
                {
                    "attempt_index": 1,
                    "failure_type": "assertion_failure" if mode != "plan" else "success",
                    "retried": mode != "plan",
                    "reason": "pytest assertion mismatch is repairable by replanning once",
                },
            )()
        ]
        self.failure_hints = ["检查 pytest 失败栈与依赖版本"]
        self.session_id = "session-1"
        self.rollback_snapshot_id = None


class _FakeStore:
    def list_sessions(self):
        record = type(
            "Record",
            (),
            {"session_id": "session-1", "description": "demo", "status": "completed"},
        )()
        return [record]

    def append_log(self, session_id: str, line: str) -> None:
        return None

    def read_log(self, session_id: str):
        assert session_id == "session-1"
        return ["plan_status=ready_to_execute", "command=pytest -q exit=1"]


def _fake_config(tmp_path: Path, *, deepseek_enabled: bool = False):
    return type(
        "Config",
        (),
        {
            "storage_dir": tmp_path / ".codepilot",
            "deepseek_enabled": deepseek_enabled,
            "deepseek_api_key": None,
            "deepseek_base_url": "https://api.deepseek.com/v1",
            "deepseek_model": "deepseek-chat",
            "deepseek_timeout": 15.0,
            "deepseek_retries": 2,
        },
    )()


def test_build_planner_client_passes_configured_retry_budget(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("codepilot.cli.DeepSeekPlannerClient", _Client)
    config = _fake_config(tmp_path, deepseek_enabled=True)
    config.deepseek_api_key = "test-key"
    config.deepseek_retries = 4

    client = __import__("codepilot.cli", fromlist=["_build_planner_client"])._build_planner_client(config)

    assert client is not None
    assert captured["retries"] == 4
    assert captured["timeout"] == 15.0


def _seed_session_store(storage_dir: Path) -> None:
    store = SessionStore(storage_dir)
    store.save_session(
        SessionRecord(
            session_id="session-1",
            description="修复失败测试",
            mode="plan",
            status="awaiting_confirmation",
            workdir="/tmp/demo",
            created_at="2026-04-23T10:00:00Z",
            risk_level="low",
            commands=["pytest -q"],
        )
    )
    store.save_session(
        SessionRecord(
            session_id="session-2",
            description="收集回归日志并修复 lint",
            mode="auto",
            status="completed",
            workdir="/tmp/demo",
            created_at="2026-04-23T10:05:00Z",
            risk_level="medium",
            commands=["pytest -q", "ruff check src tests"],
        )
    )
    store.append_log("session-2", "plan_status=ready_to_execute")
    store.append_log("session-2", "planner=deepseek")
    store.append_log("session-2", "command=pytest -q exit=0")
    store.append_log("session-2", "command=ruff check src tests exit=0")


def test_cli_run_command_prints_plan_summary(monkeypatch, capsys, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def _fake_run_task_session(**kwargs):
        calls.append(kwargs)
        return _FakeSessionResult(mode=kwargs["mode"])

    monkeypatch.setattr("codepilot.cli.run_task_session", _fake_run_task_session)
    monkeypatch.setattr("codepilot.cli.load_config", lambda project_root: _fake_config(tmp_path))

    exit_code = main(
        [
            "run",
            "--workdir",
            str(tmp_path),
            "--mode",
            "plan",
            "--max-commands",
            "4",
            "--max-edits",
            "2",
            "为项目补充计划",
        ]
    )

    assert exit_code == 0
    assert calls[0]["max_command_results"] == 4
    assert calls[0]["max_edit_results"] == 2
    output = capsys.readouterr().out
    assert "generated plan plan" in output
    assert "awaiting_confirmation" in output
    assert "检查 pytest 失败栈与依赖版本" in output
    assert "candidate_files:" in output
    assert "inspected_files:" in output
    assert "candidate_commands:" in output
    assert "edit_results:" in output
    assert "planner_trace:" in output


def test_cli_history_command_lists_sessions(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("codepilot.cli.SessionStore", lambda storage_dir: _FakeStore())
    monkeypatch.setattr("codepilot.cli.load_config", lambda project_root: _fake_config(tmp_path))

    exit_code = main(["history", "--workdir", str(tmp_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "session-1" in output
    assert "demo" in output


def test_cli_logs_command_prints_session_log(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("codepilot.cli.SessionStore", lambda storage_dir: _FakeStore())
    monkeypatch.setattr("codepilot.cli.load_config", lambda project_root: _fake_config(tmp_path))

    exit_code = main(["logs", "session-1", "--workdir", str(tmp_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "plan_status=ready_to_execute" in output
    assert "command=pytest -q exit=1" in output


def test_cli_eval_command_runs_benchmark_suite(monkeypatch, capsys, tmp_path: Path) -> None:
    fake_case = SimpleNamespace(name="case-1")
    fake_case_result = SimpleNamespace(case=fake_case, passed=True, failures=())
    fake_suite_result = SimpleNamespace(
        total=1, passed=1, failed=0, case_results=(fake_case_result,)
    )

    monkeypatch.setattr(
        "codepilot.cli.load_config",
        lambda project_root: _fake_config(tmp_path, deepseek_enabled=True),
    )
    monkeypatch.setattr("codepilot.cli._build_planner_client", lambda config: object())
    monkeypatch.setattr("codepilot.cli.load_benchmark_cases", lambda suite_path: [fake_case])
    monkeypatch.setattr(
        "codepilot.cli.run_benchmark_suite", lambda cases, planner_client: fake_suite_result
    )

    exit_code = main(["eval", "--workdir", str(tmp_path), "suite.json"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "benchmark_total: 1" in output
    assert "benchmark_passed: 1" in output
    assert "case-1 passed=True" in output


def test_cli_eval_command_runs_swebench_runner(monkeypatch, capsys, tmp_path: Path) -> None:
    fake_case = SimpleNamespace(name="django__django-12345", metadata={"dataset": "swebench"})
    fake_benchmark_result = SimpleNamespace(total=1, passed=1, failed=0, case_results=())
    fake_suite_result = SimpleNamespace(benchmark_result=fake_benchmark_result, run_results=())

    monkeypatch.setattr(
        "codepilot.cli.load_config",
        lambda project_root: _fake_config(tmp_path, deepseek_enabled=True),
    )
    monkeypatch.setattr("codepilot.cli._build_planner_client", lambda config: object())
    monkeypatch.setattr("codepilot.cli.load_benchmark_cases", lambda suite_path: [fake_case])
    monkeypatch.setattr(
        "codepilot.cli.run_swebench_suite",
        lambda cases, planner_client, **kwargs: fake_suite_result,
    )

    exit_code = main(
        [
            "eval",
            "--workdir",
            str(tmp_path),
            "--dataset-format",
            "swebench",
            "--source-repo",
            str(tmp_path / "repo"),
            "--checkout-ref",
            "deadbeef",
            "suite.json",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "benchmark_total: 1" in output
    assert "benchmark_passed: 1" in output


def test_interactive_shell_runs_default_task_and_slash_commands(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, str, Path]] = []

    def _fake_run_task_session(**kwargs):
        calls.append((kwargs["description"], kwargs["mode"], kwargs["workdir"]))
        return _FakeSessionResult(mode=kwargs["mode"])

    monkeypatch.setattr("codepilot.cli.run_task_session", _fake_run_task_session)
    monkeypatch.setattr("codepilot.cli.SessionStore", lambda storage_dir: _FakeStore())
    monkeypatch.setattr("codepilot.cli.load_config", lambda project_root: _fake_config(tmp_path))

    exit_code = run_interactive_shell(
        input_stream=io.StringIO("为仓库补充测试\n/history\n/exit\n"),
        output_stream=io.StringIO(),
        initial_workdir=tmp_path,
    )

    assert exit_code == 0
    assert calls == [("为仓库补充测试", "auto", tmp_path.resolve())]


def test_interactive_shell_plan_mode_stages_pending_plan_until_approved(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, str, Path]] = []
    output = io.StringIO()

    def _fake_run_task_session(**kwargs):
        calls.append((kwargs["description"], kwargs["mode"], kwargs["workdir"]))
        return _FakeSessionResult(mode=kwargs["mode"])

    monkeypatch.setattr("codepilot.cli.run_task_session", _fake_run_task_session)
    monkeypatch.setattr("codepilot.cli.SessionStore", lambda storage_dir: _FakeStore())
    monkeypatch.setattr("codepilot.cli.load_config", lambda project_root: _fake_config(tmp_path))

    exit_code = run_interactive_shell(
        input_stream=io.StringIO("/mode plan\n修复失败测试\n/status\n/approve\n/exit\n"),
        output_stream=output,
        initial_workdir=tmp_path,
    )

    assert exit_code == 0
    assert calls == [
        ("修复失败测试", "plan", tmp_path.resolve()),
        ("修复失败测试", "auto", tmp_path.resolve()),
    ]
    text = output.getvalue()
    assert "Shell Status" in text
    assert "pending_plan    : 修复失败测试" in text
    assert "继续讨论计划 /approve 执行 /cancel 取消" in text


def test_interactive_shell_supports_at_aliases_for_logs_and_restore(
    monkeypatch, tmp_path: Path
) -> None:
    restored: list[str] = []
    output = io.StringIO()

    class _FakeSnapshotManager:
        def __init__(self, storage_dir: Path) -> None:
            self.storage_dir = storage_dir
            self.snapshots_dir = storage_dir / "snapshots"

        def restore_snapshot(self, snapshot_id: str) -> list[str]:
            restored.append(snapshot_id)
            return ["src/codepilot/cli.py"]

    monkeypatch.setattr("codepilot.cli.SessionStore", lambda storage_dir: _FakeStore())
    monkeypatch.setattr(
        "codepilot.cli.WorkspaceSnapshotManager",
        lambda storage_dir: _FakeSnapshotManager(storage_dir),
    )
    monkeypatch.setattr("codepilot.cli.load_config", lambda project_root: _fake_config(tmp_path))

    exit_code = run_interactive_shell(
        input_stream=io.StringIO("@session-1\n@snapshot-42\n/exit\n"),
        output_stream=output,
        initial_workdir=tmp_path,
    )

    assert exit_code == 0
    text = output.getvalue()
    assert "plan_status=ready_to_execute" in text
    assert "restored 1 files" in text
    assert restored == ["snapshot-42"]


def test_interactive_shell_supports_workspace_inspection_commands(
    monkeypatch, tmp_path: Path
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    demo_file = src_dir / "demo.py"
    demo_file.write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
    output = io.StringIO()

    monkeypatch.setattr("codepilot.cli.SessionStore", lambda storage_dir: _FakeStore())
    monkeypatch.setattr("codepilot.cli.load_config", lambda project_root: _fake_config(tmp_path))

    exit_code = run_interactive_shell(
        input_stream=io.StringIO(
            "/files src/**/*.py\n"
            "/grep hello **/*.py\n"
            "/read src/demo.py 1:2\n"
            "/replace src/demo.py hello world\n"
            "/exit\n"
        ),
        output_stream=output,
        initial_workdir=tmp_path,
    )

    assert exit_code == 0
    text = output.getvalue()
    assert str(demo_file) in text
    assert "src/demo.py:2:     return 'hello'" in text
    assert "1|def greet():" in text
    assert "2|    return 'hello'" in text
    assert "syntax_check: ok" in text
    assert "+    return 'world'" in text
    assert "world" in demo_file.read_text(encoding="utf-8")


def test_interactive_shell_supports_exec_and_cd_commands(monkeypatch, tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    output = io.StringIO()

    monkeypatch.setattr("codepilot.cli.SessionStore", lambda storage_dir: _FakeStore())
    monkeypatch.setattr("codepilot.cli.load_config", lambda project_root: _fake_config(tmp_path))

    exit_code = run_interactive_shell(
        input_stream=io.StringIO("/exec pwd\n/cd nested\n/exec pwd\n/status\n/exit\n"),
        output_stream=output,
        initial_workdir=tmp_path,
    )

    assert exit_code == 0
    text = output.getvalue()
    assert "command: pwd" in text
    assert f"cwd: {tmp_path.resolve()}" in text
    assert f"cwd => {nested.resolve()}" in text
    assert f"cwd: {nested.resolve()}" in text
    assert "shell_session   : shell-" in text
    assert "shell_cwd       : " in text
    assert "last_shell_cmd  : pwd" in text
    assert "last_shell_exit : 0" in text


def test_interactive_shell_run_mode_can_edit_code_and_verify_with_pytest(
    monkeypatch, tmp_path: Path
) -> None:
    src_dir = tmp_path / "src"
    tests_dir = tmp_path / "tests"
    src_dir.mkdir()
    tests_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    app_file = src_dir / "app.py"
    app_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "ROOT = Path(__file__).resolve().parent\n"
        "if str(ROOT) not in sys.path:\n"
        "    sys.path.insert(0, str(ROOT))\n",
        encoding="utf-8",
    )
    (tests_dir / "test_app.py").write_text(
        "from src.app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    output = io.StringIO()

    class _PlannerClient:
        def generate_plan(self, **kwargs):
            return PlannerSuggestion(
                summary="修复 add 实现并验证 pytest",
                steps=("阅读 src/app.py 与 tests/test_app.py", "修改实现", "运行 pytest -q"),
                candidate_commands=["pytest -q"],
                file_reads=["src/app.py", "tests/test_app.py"],
                file_edits=[
                    FileEditSuggestion(
                        path="src/app.py",
                        old_string="return a - b\n",
                        new_string="return a + b\n",
                        replace_all=False,
                    )
                ],
            )

    monkeypatch.setattr(
        "codepilot.cli.load_config",
        lambda project_root: type(
            "Config",
            (),
            {
                "storage_dir": tmp_path / ".codepilot",
                "deepseek_enabled": True,
                "deepseek_api_key": "test-key",
                "deepseek_base_url": "https://api.deepseek.com/v1",
                "deepseek_model": "deepseek-chat",
                "deepseek_timeout": 15.0,
                "deepseek_retries": 2,
            },
        )(),
    )
    monkeypatch.setattr("codepilot.cli.DeepSeekPlannerClient", lambda **kwargs: _PlannerClient())

    exit_code = run_interactive_shell(
        input_stream=io.StringIO("/run 修复 add\n/exit\n"),
        output_stream=output,
        initial_workdir=tmp_path,
    )

    assert exit_code == 0
    text = output.getvalue()
    assert "summary: 修复 add 实现并验证 pytest" in text
    assert "edit_results:" in text
    assert "applied=True reverted=False syntax=ok" in text
    assert "command: pytest -q => 0" in text
    assert "failure=success retried=False reason=verification passed" in text
    assert "return a + b" in app_file.read_text(encoding="utf-8")


def test_main_without_arguments_starts_interactive_shell(monkeypatch) -> None:
    monkeypatch.setattr("codepilot.cli.run_interactive_shell", lambda **kwargs: 7)

    exit_code = main([])

    assert exit_code == 7


def test_main_with_tui_flag_starts_tui_shell(monkeypatch, tmp_path: Path) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(
        "codepilot.cli.run_tui_shell",
        lambda **kwargs: calls.append(kwargs["initial_workdir"]) or 9,
    )

    exit_code = main(["--tui", "--workdir", str(tmp_path)])

    assert exit_code == 9
    assert calls == [tmp_path.resolve()]


def test_interactive_shell_dashboard_shows_latest_session(monkeypatch, tmp_path: Path) -> None:
    output = io.StringIO()
    demo_root = Path("/tmp/demo")
    (demo_root / "src").mkdir(parents=True, exist_ok=True)
    (demo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")

    def _fake_run_task_session(**kwargs):
        return _FakeSessionResult(mode=kwargs["mode"])

    monkeypatch.setattr("codepilot.cli.run_task_session", _fake_run_task_session)
    monkeypatch.setattr("codepilot.cli.SessionStore", lambda storage_dir: _FakeStore())
    monkeypatch.setattr("codepilot.cli.load_config", lambda project_root: _fake_config(tmp_path))

    exit_code = run_interactive_shell(
        input_stream=io.StringIO("/run 修复失败测试\n/dashboard\n/exit\n"),
        output_stream=output,
        initial_workdir=tmp_path,
    )

    assert exit_code == 0
    text = output.getvalue()
    assert "Latest Session" in text
    assert "latest_session  : session-1" in text
    assert "Retry Trace" in text
    assert "Planner Trace" in text
    assert "Failure Targets" in text
    assert "src/app.py" in text


def test_interactive_shell_reports_edit_failures_without_crashing(
    monkeypatch, tmp_path: Path
) -> None:
    output = io.StringIO()

    def _failing_run_task_session(**kwargs):
        raise ValueError("old string appears multiple times")

    monkeypatch.setattr("codepilot.cli.run_task_session", _failing_run_task_session)
    monkeypatch.setattr("codepilot.cli.SessionStore", lambda storage_dir: _FakeStore())
    monkeypatch.setattr("codepilot.cli.load_config", lambda project_root: _fake_config(tmp_path))

    exit_code = run_interactive_shell(
        input_stream=io.StringIO("/run 修复失败测试\n/exit\n"),
        output_stream=output,
        initial_workdir=tmp_path,
    )

    assert exit_code == 0
    text = output.getvalue()
    assert "error: old string appears multiple times" in text
    assert "bye" in text


def test_build_completion_candidates_include_commands_sessions_and_snapshots(
    tmp_path: Path,
) -> None:
    class _StoreWithSessions:
        def list_sessions(self):
            record = type(
                "Record",
                (),
                {"session_id": "session-1", "description": "demo", "status": "completed"},
            )()
            return [record]

    class _SnapshotManagerWithFiles:
        snapshots_dir = tmp_path / ".codepilot" / "snapshots"

    (_SnapshotManagerWithFiles.snapshots_dir / "snapshot-20260417120000000000").mkdir(
        parents=True,
        exist_ok=True,
    )

    state = InteractiveShellState(workdir=tmp_path, mode="auto")
    candidates = build_completion_candidates(
        state,
        store=_StoreWithSessions(),
        snapshot_manager=_SnapshotManagerWithFiles(),
    )

    assert "/mode auto" in candidates
    assert "/mode plan" in candidates
    assert "/plan " in candidates
    assert "/approve" in candidates
    assert "/status" in candidates
    assert "/dashboard" in candidates
    assert "/files " in candidates
    assert "/grep " in candidates
    assert "/read " in candidates
    assert "/replace " in candidates
    assert f"/workdir {tmp_path}" in candidates
    assert "@session-1" in candidates
    assert "@snapshot-20260417120000000000" in candidates


def test_configure_shell_readline_registers_completion_and_history(tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    class _FakeReadline:
        def parse_and_bind(self, value: str) -> None:
            calls["parse_and_bind"] = value

        def set_completer(self, completer) -> None:
            calls["completer"] = completer

        def set_history_length(self, length: int) -> None:
            calls["history_length"] = length

        def read_history_file(self, path: str) -> None:
            calls["read_history_file"] = path

    history_file = tmp_path / ".codepilot" / "cli-history.txt"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text("/history\n", encoding="utf-8")
    state = InteractiveShellState(workdir=tmp_path)

    snapshot_manager = type(
        "SnapshotManager",
        (),
        {"snapshots_dir": tmp_path / ".codepilot" / "snapshots"},
    )()

    configure_shell_readline(
        state,
        storage_dir=tmp_path / ".codepilot",
        readline_backend=_FakeReadline(),
        store=_FakeStore(),
        snapshot_manager=snapshot_manager,
    )

    assert calls["parse_and_bind"] == "tab: complete"
    assert calls["history_length"] == 200
    assert calls["read_history_file"] == str(history_file)
    completer = calls["completer"]
    assert completer("/ap", 0) == "/approve"
    assert completer("/mo", 0) == "/mode auto"
    assert completer("/mo", 1) == "/mode plan"


def test_render_shell_intro_uses_more_natural_guidance(tmp_path: Path) -> None:
    intro = render_shell_intro(InteractiveShellState(workdir=tmp_path, mode="auto"))

    assert "CodePilot // Agent Shell" in intro
    assert "默认自动执行；/mode plan 可切回仅规划。" in intro
    assert (
        "examples  : /run 修复失败测试 | /mode plan | /exec pytest -q | "
        "/dashboard | /files src/**/*.py" in intro
    )
    assert str(tmp_path) in intro


def test_render_tui_snapshot_contains_multi_panel_sections(tmp_path: Path) -> None:
    state = InteractiveShellState(
        workdir=tmp_path,
        mode="plan",
        pending_description="修复失败测试",
        pending_result=_FakeSessionResult(mode="plan"),
        last_result=_FakeSessionResult(mode="auto"),
    )

    snapshot = render_tui_snapshot(state, width=100, height=28)

    assert "CodePilot TUI" in snapshot
    assert "LEFT // navigator [sessions]" in snapshot
    assert "RIGHT // detail [diff]" in snapshot
    assert "BOTTOM // task input [active]" in snapshot
    assert "focus: input" in snapshot
    assert "left view: sessions" in snapshot
    assert "latest diff:" in snapshot
    assert "+return 42" in snapshot
    assert "pending: 修复失败测试" in snapshot


def test_render_tui_snapshot_supports_detail_view_switches(tmp_path: Path) -> None:
    state = InteractiveShellState(
        workdir=tmp_path,
        mode="plan",
        pending_description="修复失败测试",
        pending_result=_FakeSessionResult(mode="plan"),
        last_result=_FakeSessionResult(mode="auto"),
    )

    planner_snapshot = render_tui_snapshot(
        state,
        width=100,
        height=28,
        active_panel="detail",
        detail_view="planner_trace",
    )
    failure_snapshot = render_tui_snapshot(
        state,
        width=100,
        height=28,
        active_panel="input",
        detail_view="failure_hints",
    )

    assert "LEFT // navigator [sessions]" in planner_snapshot
    assert "RIGHT // detail [planner_trace] [active]" in planner_snapshot
    assert "planner trace:" in planner_snapshot
    assert "attempt=1 source=deepseek" in planner_snapshot
    assert "focus: detail" in planner_snapshot

    assert "RIGHT // detail [failure_hints]" in failure_snapshot
    assert "BOTTOM // task input [active]" in failure_snapshot
    assert "failure hints:" in failure_snapshot
    assert "检查 pytest 失败栈与依赖版本" in failure_snapshot
    assert "focus: input" in failure_snapshot


def test_render_tui_snapshot_supports_detail_offset_for_long_views(tmp_path: Path) -> None:
    result = _FakeSessionResult(mode="auto")
    result.failure_hints = [f"hint-{index}" for index in range(1, 9)]
    state = InteractiveShellState(
        workdir=tmp_path,
        mode="plan",
        pending_description="修复失败测试",
        pending_result=_FakeSessionResult(mode="plan"),
        last_result=result,
    )

    snapshot = render_tui_snapshot(
        state,
        width=100,
        height=28,
        active_panel="detail",
        detail_view="failure_hints",
        detail_offset=2,
    )

    assert "detail offset: 2" in snapshot
    assert "failure hints [3:7]" in snapshot
    assert "hint-3" in snapshot
    assert "hint-6" in snapshot
    assert "hint-1" not in snapshot
    assert "hint-2" not in snapshot


def test_render_tui_snapshot_clamps_detail_offset(tmp_path: Path) -> None:
    result = _FakeSessionResult(mode="auto")
    result.failure_hints = [f"hint-{index}" for index in range(1, 5)]
    state = InteractiveShellState(
        workdir=tmp_path,
        mode="plan",
        pending_description="修复失败测试",
        pending_result=_FakeSessionResult(mode="plan"),
        last_result=result,
    )

    snapshot = render_tui_snapshot(
        state,
        width=100,
        height=28,
        active_panel="detail",
        detail_view="failure_hints",
        detail_offset=99,
    )

    assert "detail offset: 1" in snapshot
    assert "failure hints [2:6]" in snapshot
    assert "hint-2" in snapshot
    assert "hint-4" in snapshot


def test_render_tui_snapshot_supports_session_navigation_summary(tmp_path: Path) -> None:
    _seed_session_store(tmp_path / ".codepilot")
    state = InteractiveShellState(workdir=tmp_path, mode="plan")

    snapshot = render_tui_snapshot(
        state,
        width=100,
        height=28,
        active_panel="session",
        left_panel_view="sessions",
        left_session_index=0,
        detail_view="session_summary",
    )

    assert "LEFT // navigator [sessions] [active]" in snapshot
    assert "> session-2 completed 收集回归日志并修复 lint" in snapshot
    assert "RIGHT // detail [session_summary]" in snapshot
    assert "session summary:" in snapshot
    assert "session: session-2" in snapshot
    assert "commands: 2" in snapshot
    assert "logs: 4 lines" in snapshot


def test_render_tui_snapshot_supports_log_navigation_context(tmp_path: Path) -> None:
    _seed_session_store(tmp_path / ".codepilot")
    state = InteractiveShellState(workdir=tmp_path, mode="plan")

    snapshot = render_tui_snapshot(
        state,
        width=100,
        height=28,
        active_panel="session",
        left_panel_view="logs",
        left_session_index=0,
        left_log_index=2,
        detail_view="log_context",
    )

    assert "LEFT // navigator [logs] [active]" in snapshot
    assert "view: logs (session-2)" in snapshot
    assert "> 3. command=pytest -q exit=0" in snapshot
    assert "RIGHT // detail [log_context]" in snapshot
    assert "log context: session-2" in snapshot
    assert "log lines [1:4]" in snapshot
    assert "> 3. command=pytest -q exit=0" in snapshot


def test_render_tui_snapshot_clamps_session_selection(tmp_path: Path) -> None:
    _seed_session_store(tmp_path / ".codepilot")
    state = InteractiveShellState(workdir=tmp_path, mode="plan")

    snapshot = render_tui_snapshot(
        state,
        width=100,
        height=28,
        active_panel="session",
        left_panel_view="sessions",
        left_session_index=99,
        detail_view="session_summary",
    )

    assert "> session-1 awaiting_confirmation 修复失败测试" in snapshot
    assert "session: session-1" in snapshot
