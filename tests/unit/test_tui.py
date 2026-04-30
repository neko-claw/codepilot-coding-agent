from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from codepilot.ui.tui import (
    _handle_tui_keypress,
    _TuiDetailState,
    _TuiLeftState,
    _TuiSessionState,
    _TuiShellState,
    render_tui_snapshot,
    run_tui_shell,
)


def test_run_tui_shell_falls_back_to_text_snapshot(tmp_path: Path) -> None:
    buffer = StringIO()

    exit_code = run_tui_shell(initial_workdir=tmp_path, output_stream=buffer)

    snapshot = buffer.getvalue()
    assert exit_code == 0
    assert "CodePilot TUI" in snapshot
    assert "workspace:" in snapshot
    assert "LEFT // navigator [sessions]" in snapshot
    assert "RIGHT // detail [diff]" in snapshot
    assert "BOTTOM // task input [active]" in snapshot


def test_tui_keypresses_switch_panels_and_navigation() -> None:
    state = _TuiShellState(
        workdir=Path("/tmp/workspace"),
        storage_dir=Path("/tmp/workspace/.codepilot"),
        mode="plan",
        session=_TuiSessionState(
            pending_description="修复失败测试",
            pending_result=None,
            last_result=None,
        ),
        left=_TuiLeftState(view="sessions", session_index=0, log_index=0),
        detail=_TuiDetailState(view="diff", offset=0),
    )

    assert state.active_panel == "input"

    _handle_tui_keypress(state, ord("\t"))
    assert state.active_panel == "session"

    _handle_tui_keypress(state, ord("\t"))
    assert state.active_panel == "detail"

    _handle_tui_keypress(state, ord("\t"))
    assert state.active_panel == "input"

    _handle_tui_keypress(state, ord("s"))
    assert state.left.view == "sessions"
    assert state.detail.view == "session_summary"
    assert state.active_panel == "session"

    _handle_tui_keypress(state, ord("j"))
    assert state.left.session_index == 1

    _handle_tui_keypress(state, ord("g"))
    assert state.left.view == "logs"
    assert state.detail.view == "log_context"

    _handle_tui_keypress(state, ord("p"))
    assert state.detail.view == "planner_trace"
    assert state.active_panel == "detail"

    _handle_tui_keypress(state, ord("j"))
    assert state.detail.offset == 1

    _handle_tui_keypress(state, ord("k"))
    assert state.detail.offset == 0


def test_tui_input_panel_accepts_prompt_submission(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def _fake_run_task_session(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            session_id="session-xyz",
            plan=SimpleNamespace(
                status="ready_to_execute",
                can_execute=True,
                next_action="execute_plan",
                summary="generated plan",
                steps=("Read files", "Run tests"),
                candidate_files=[],
                candidate_commands=[],
                risk=SimpleNamespace(level="low", reason="safe"),
                user_options=["execute_plan"],
            ),
            request=SimpleNamespace(workdir=str(tmp_path)),
            github_snapshot=None,
            inspected_files=[],
            edit_results=[],
            command_results=[],
            planner_trace=[],
            retry_trace=[],
            failure_hints=[],
            rollback_snapshot_id=None,
        )

    monkeypatch.setattr("codepilot.ui.tui.run_task_session", _fake_run_task_session)

    state = _TuiShellState(
        workdir=tmp_path,
        storage_dir=tmp_path / ".codepilot",
        mode="auto",
    )

    assert state.active_panel == "input"

    for key in "修复失败测试":
        _handle_tui_keypress(state, ord(key))
    _handle_tui_keypress(state, 10)

    assert calls[0]["description"] == "修复失败测试"
    assert calls[0]["mode"] == "auto"
    assert calls[0]["workdir"] == tmp_path
    assert state.input.history[0] == "修复失败测试"
    assert state.input.draft == ""
    assert state.session.last_result is not None


def test_tui_input_panel_supports_cursor_editing(tmp_path: Path) -> None:
    state = _TuiShellState(
        workdir=tmp_path,
        storage_dir=tmp_path / ".codepilot",
        mode="auto",
    )
    state.input.draft = "abc"
    state.input.cursor = 3

    _handle_tui_keypress(state, 260)  # left arrow
    _handle_tui_keypress(state, 260)  # left arrow
    _handle_tui_keypress(state, ord("X"))
    _handle_tui_keypress(state, 262)  # home
    _handle_tui_keypress(state, ord("Y"))
    _handle_tui_keypress(state, 360)  # end
    _handle_tui_keypress(state, ord("Z"))

    assert state.input.draft == "YaXbcZ"
    assert state.input.cursor == 6


def test_tui_input_panel_recalls_history_with_arrow_keys(tmp_path: Path) -> None:
    state = _TuiShellState(
        workdir=tmp_path,
        storage_dir=tmp_path / ".codepilot",
        mode="auto",
    )
    state.input.history = ["third", "second", "first"]

    _handle_tui_keypress(state, 259)  # up arrow
    assert state.input.draft == "third"
    assert state.input.history_index == 0

    _handle_tui_keypress(state, 259)
    assert state.input.draft == "second"
    assert state.input.history_index == 1

    _handle_tui_keypress(state, 258)  # down arrow
    assert state.input.draft == "third"
    assert state.input.history_index == 0

    _handle_tui_keypress(state, 258)
    assert state.input.draft == ""
    assert state.input.history_index is None


def test_render_tui_snapshot_centers_task_input_workflow(tmp_path: Path) -> None:
    state = _TuiShellState(
        workdir=tmp_path,
        storage_dir=tmp_path / ".codepilot",
        mode="auto",
    )

    snapshot = render_tui_snapshot(state, width=100, height=28)

    assert "focus: input" in snapshot
    assert "BOTTOM // task input [active]" in snapshot
    assert "compose:" in snapshot
    assert "cursor: 0" in snapshot
    assert "history: new" in snapshot
    assert "按 Enter 执行" in snapshot



def test_render_tui_snapshot_reflects_panel_switches(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "tests" / "test_demo.py").write_text("assert True\n", encoding="utf-8")
    last_result = type(
        "Result",
        (),
        {
            "failure_hints": ["hint-1", "hint-2", "hint-3"],
            "command_results": [
                type(
                    "CommandResult",
                    (),
                    {
                        "command": "pytest -q",
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": f"Traceback in {tmp_path / 'tests' / 'test_demo.py'}",
                    },
                )()
            ],
            "edit_results": [
                type(
                    "EditResult",
                    (),
                    {
                        "path": str(tmp_path / 'src' / 'app.py'),
                        "applied": False,
                        "reverted": False,
                        "syntax_check": "error: invalid syntax",
                        "diff": [],
                    },
                )()
            ],
            "request": type("Request", (), {"workdir": str(tmp_path)})(),
        },
    )()
    state = _TuiShellState(
        workdir=tmp_path,
        storage_dir=tmp_path / ".codepilot",
        mode="auto",
        session=_TuiSessionState(
            pending_description="继续改代码",
            pending_result=None,
            last_result=last_result,
        ),
        left=_TuiLeftState(view="logs", session_index=0, log_index=0),
        detail=_TuiDetailState(view="failure_hints", offset=2),
    )

    snapshot = render_tui_snapshot(state, width=100, height=28)

    assert "LEFT // navigator [logs]" in snapshot
    assert "RIGHT // detail [failure_hints]" in snapshot
    assert "BOTTOM // task input [active]" in snapshot
    assert "pending: 继续改代码" in snapshot
    assert "hint-3" in snapshot
    assert "target files" in snapshot
    assert "src/app.py" in snapshot
