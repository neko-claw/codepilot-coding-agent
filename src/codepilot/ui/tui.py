"""Minimal curses-based TUI skeleton for CodePilot."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import shorten, wrap
from typing import TYPE_CHECKING, TextIO

from codepilot.core.config import load_config
from codepilot.runtime.session import run_task_session, _extract_failure_target_files
from codepilot.storage.session_store import SessionRecord, SessionStore

try:  # pragma: no cover - terminal capability depends on runtime
    import curses
except ImportError:  # pragma: no cover - platform dependent
    curses = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from codepilot.cli import InteractiveShellState


@dataclass(slots=True)
class _TuiDetailState:
    view: str = "diff"
    offset: int = 0


@dataclass(slots=True)
class _TuiLeftState:
    view: str = "sessions"
    session_index: int = 0
    log_index: int = 0


@dataclass(slots=True)
class _TuiSessionState:
    pending_description: str | None = None
    pending_result: object | None = None
    last_result: object | None = None


@dataclass(slots=True)
class _TuiInputState:
    draft: str = ""
    history: list[str] = field(default_factory=list)
    history_index: int | None = None
    saved_draft: str = ""
    cursor: int = 0
    busy: bool = False
    last_submitted: str | None = None


@dataclass(slots=True)
class _TuiShellState:
    workdir: Path
    storage_dir: Path
    mode: str = "auto"
    session: _TuiSessionState = field(default_factory=_TuiSessionState)
    active_panel: str = "input"
    left: _TuiLeftState = field(default_factory=_TuiLeftState)
    detail: _TuiDetailState = field(default_factory=_TuiDetailState)
    input: _TuiInputState = field(default_factory=_TuiInputState)



@dataclass(frozen=True, slots=True)
class _TuiNavigationContext:
    left_view: str
    sessions: list[SessionRecord]
    selected_session: SessionRecord | None
    selected_session_index: int
    selected_logs: list[str]
    selected_log_index: int


_BOX_WIDTH = 46
_LEFT_WINDOW_SIZE = 6
_DETAIL_WINDOW_SIZE = 5


def _state_pending_description(state: InteractiveShellState) -> str | None:
    session = getattr(state, "session", None)
    if session is not None:
        return getattr(session, "pending_description", None)
    return getattr(state, "pending_description", None)


def _state_pending_result(state: InteractiveShellState):
    session = getattr(state, "session", None)
    if session is not None:
        return getattr(session, "pending_result", None)
    return getattr(state, "pending_result", None)


def _state_last_result(state: InteractiveShellState):
    session = getattr(state, "session", None)
    if session is not None:
        return getattr(session, "last_result", None)
    return getattr(state, "last_result", None)


def _state_task_draft(state: InteractiveShellState) -> str:
    input_state = getattr(state, "input", None)
    if input_state is not None:
        return getattr(input_state, "draft", "")
    return getattr(state, "task_draft", "")


def _state_recent_tasks(state: InteractiveShellState) -> list[str]:
    input_state = getattr(state, "input", None)
    if input_state is not None:
        return list(getattr(input_state, "history", []) or [])
    return list(getattr(state, "recent_tasks", []) or [])


def render_tui_snapshot(  # pylint: disable=too-many-arguments,too-many-locals
    state: InteractiveShellState,
    *,
    width: int = 100,
    height: int = 28,
    active_panel: str | None = None,
    left_panel_view: str | None = None,
    left_session_index: int | None = None,
    left_log_index: int | None = None,
    detail_view: str | None = None,
    detail_offset: int | None = None,
) -> str:
    """Render a string snapshot of the multi-panel TUI layout."""
    del width, height
    resolved_panel = active_panel or getattr(state, "active_panel", "session")
    left_state = getattr(state, "left", None)
    resolved_left_view = (
        left_panel_view
        or getattr(left_state, "view", None)
        or getattr(
            state,
            "left_view",
            "sessions",
        )
    )
    requested_session_index = left_session_index
    if requested_session_index is None:
        requested_session_index = getattr(left_state, "session_index", None)
    if requested_session_index is None:
        requested_session_index = getattr(state, "left_session_index", 0)
    requested_log_index = left_log_index
    if requested_log_index is None:
        requested_log_index = getattr(left_state, "log_index", None)
    if requested_log_index is None:
        requested_log_index = getattr(state, "left_log_index", 0)
    navigation = _resolve_navigation_context(
        state,
        left_view=resolved_left_view,
        requested_session_index=requested_session_index,
        requested_log_index=requested_log_index,
    )

    detail_state = getattr(state, "detail", None)
    resolved_view = (
        detail_view
        or getattr(detail_state, "view", None)
        or getattr(
            state,
            "detail_view",
            "diff",
        )
    )
    requested_offset = detail_offset
    if requested_offset is None:
        requested_offset = getattr(detail_state, "offset", None)
    if requested_offset is None:
        requested_offset = getattr(state, "detail_offset", 0)
    detail_lines, resolved_offset = _detail_panel_lines(
        state,
        navigation,
        resolved_view,
        requested_offset,
    )
    sections = [
        _boxed(
            "CodePilot TUI",
            [
                f"workspace: {state.workdir}",
                f"mode: {state.mode}",
                f"pending: {_state_pending_description(state) or 'none'}",
                f"focus: {resolved_panel}",
                f"task draft: {_state_task_draft(state) or 'empty'}",
                f"left view: {navigation.left_view}",
                f"detail view: {resolved_view}",
                f"detail offset: {resolved_offset}",
                (
                    "hint: type prompt in input | enter run | tab cycle | s sessions | g logs | "
                    "d diff | p planner trace | f failure hints | j/k move-or-scroll | q quit."
                ),
            ],
        ),
        _boxed(
            _left_panel_title(resolved_panel, navigation.left_view),
            _left_panel_lines(navigation),
        ),
        _boxed(
            _detail_panel_title(resolved_panel, resolved_view),
            detail_lines,
        ),
        _boxed(
            _panel_title("BOTTOM // task input", resolved_panel == "input"),
            _bottom_panel_lines(state),
        ),
    ]
    return "\n\n".join(sections)


def run_tui_shell(
    *,
    initial_workdir: str | Path | None = None,
    output_stream: TextIO | None = None,
) -> int:
    """Run a minimal TUI shell; fall back to a textual snapshot when TTY/curses is unavailable."""
    workdir = Path(initial_workdir or Path.cwd()).resolve()
    state = _TuiShellState(workdir=workdir, storage_dir=load_config(workdir).storage_dir)
    current_output = output_stream or sys.stdout
    if curses is None or current_output is not sys.stdout or not sys.stdout.isatty():
        current_output.write(render_tui_snapshot(state))
        current_output.write("\n")
        current_output.flush()
        return 0
    return curses.wrapper(lambda screen: _curses_main(screen, state))


def _curses_main(screen, state: InteractiveShellState) -> int:  # pragma: no cover - interactive
    curses.curs_set(0)
    screen.nodelay(False)
    while True:
        height, width = screen.getmaxyx()
        screen.erase()
        snapshot_lines = render_tui_snapshot(
            state,
            width=width,
            height=height,
        ).splitlines()
        for row_index, line in enumerate(snapshot_lines):
            if row_index >= height - 1:
                break
            screen.addnstr(row_index, 0, line, max(1, width - 1))
        screen.refresh()
        key = screen.getch()
        if key in {ord("q"), ord("Q")}:
            return 0
        _handle_tui_keypress(state, key)


def _left_panel_lines(navigation: _TuiNavigationContext) -> list[str]:
    if navigation.left_view == "logs":
        return _left_log_lines(navigation)
    return _left_session_lines(navigation)


def _detail_panel_lines(  # pylint: disable=too-many-return-statements
    state: InteractiveShellState,
    navigation: _TuiNavigationContext,
    detail_view: str,
    detail_offset: int,
) -> tuple[list[str], int]:
    last_result = _state_last_result(state)
    selected_session = navigation.selected_session
    if detail_view == "session_summary":
        return _session_summary_lines(selected_session, navigation.selected_logs)
    if detail_view == "log_context":
        return _log_context_lines(
            selected_session,
            navigation.selected_logs,
            navigation.selected_log_index,
        )
    if last_result is None:
        return [f"{detail_view}: none"], 0
    if selected_session is not None and getattr(last_result, "session_id", None) not in {
        None,
        selected_session.session_id,
    }:
        return _session_summary_lines(selected_session, navigation.selected_logs), 0
    if detail_view == "planner_trace":
        planner_trace = getattr(last_result, "planner_trace", [])
        trace_lines = [_format_planner_trace_line(item) for item in planner_trace] or ["none"]
        return _slice_detail_lines("planner trace", trace_lines, detail_offset)
    if detail_view == "failure_hints":
        failure_hints = getattr(last_result, "failure_hints", []) or ["none"]
        target_files = _failure_target_files(last_result) or ["none"]
        lines = [*failure_hints, "target files:", *target_files[:3]]
        return _slice_detail_lines("failure hints", lines, detail_offset)
    if detail_view == "target_files":
        target_files = _failure_target_files(last_result) or ["none"]
        return _slice_detail_lines("target files", target_files, detail_offset)
    diff_lines = _latest_diff(last_result)
    failure_hints = getattr(last_result, "failure_hints", []) or ["none"]
    target_files = _failure_target_files(last_result) or ["none"]
    planner_trace = getattr(last_result, "planner_trace", [])
    trace_lines = [_format_planner_trace_line(item) for item in planner_trace[:3]] or ["none"]
    lines = [
        "latest diff:",
        *diff_lines,
        "failure hints:",
        *failure_hints[:3],
        "target files:",
        *target_files[:3],
        "planner trace:",
        *trace_lines,
    ]
    return lines, 0


def _bottom_panel_lines(state: InteractiveShellState) -> list[str]:
    prompt = f"codepilot[{state.mode}] {state.workdir}> "
    draft = _state_task_draft(state)
    history = _state_recent_tasks(state)
    latest_task = history[0] if history else _state_pending_description(state) or "none"
    input_state = getattr(state, "input", None)
    cursor = getattr(input_state, "cursor", len(draft)) if input_state is not None else len(draft)
    history_index = getattr(input_state, "history_index", None) if input_state is not None else None
    return [
        f"prompt: {shorten(prompt, width=80, placeholder='...')}",
        f"compose: {draft or '输入任务 prompt，按 Enter 执行'}",
        f"cursor: {cursor}",
        f"history: {history_index if history_index is not None else 'new'}",
        f"latest task: {shorten(str(latest_task), width=80, placeholder='...')}",
        "status: prompt-first task composer active",
        "commands: /run <goal> | /mode plan | /dashboard | /files src/**/*.py",
    ]


def _latest_diff(result) -> list[str]:
    for edit_result in getattr(result, "edit_results", []):
        diff = getattr(edit_result, "diff", [])
        if diff:
            return diff[:6]
    return ["none"]


def _failure_target_files(result) -> list[str]:
    command_results = list(getattr(result, "command_results", []))
    edit_results = list(getattr(result, "edit_results", []))
    workdir_value = getattr(getattr(result, "request", None), "workdir", ".")
    workdir = Path(workdir_value).resolve()
    return _extract_failure_target_files(command_results, edit_results, workdir)


def _slice_detail_lines(
    label: str,
    lines: list[str],
    detail_offset: int,
) -> tuple[list[str], int]:
    total = len(lines)
    if total <= _DETAIL_WINDOW_SIZE:
        resolved_offset = 0
    else:
        max_offset = total - _DETAIL_WINDOW_SIZE
        resolved_offset = max(0, min(detail_offset, max_offset))
    start = resolved_offset
    end = min(total, resolved_offset + _DETAIL_WINDOW_SIZE)
    window = lines[start:end]
    return [f"{label}:", f"{label} [{start + 1}:{end}]", *window], resolved_offset


def _handle_tui_keypress(state: _TuiShellState, key: int) -> None:  # pylint: disable=too-many-return-statements
    if key in {9, curses.KEY_BTAB if curses is not None else -1}:
        state.active_panel = _next_panel(state.active_panel)
        return
    if key in {ord("s"), ord("S")}:
        state.left.view = "sessions"
        state.active_panel = "session"
        state.detail.view = "session_summary"
        state.detail.offset = 0
        return
    if key in {ord("g"), ord("G")}:
        state.left.view = "logs"
        state.active_panel = "session"
        state.detail.view = "log_context"
        state.detail.offset = 0
        return
    if key in {ord("d"), ord("D")}:
        state.detail.view = "diff"
        state.detail.offset = 0
        state.active_panel = "detail"
        return
    if key in {ord("p"), ord("P")}:
        state.detail.view = "planner_trace"
        state.detail.offset = 0
        state.active_panel = "detail"
        return
    if key in {ord("f"), ord("F")}:
        state.detail.view = "failure_hints"
        state.detail.offset = 0
        state.active_panel = "detail"
        return
    if key in {ord("t"), ord("T")}:
        state.detail.view = "target_files"
        state.detail.offset = 0
        state.active_panel = "detail"
        return
    if state.active_panel == "input":
        if key in {10, 13}:
            _submit_input_task(state)
            return
        if key == 27:
            state.input.draft = ""
            _reset_input_history_navigation(state)
            state.input.cursor = 0
            return
        if key in {8, 127, curses.KEY_BACKSPACE if curses is not None else -1}:
            _delete_input_before_cursor(state)
            return
        if key in {260, curses.KEY_LEFT if curses is not None else -1}:
            _move_input_cursor(state, -1)
            return
        if key in {261, curses.KEY_RIGHT if curses is not None else -1}:
            _move_input_cursor(state, 1)
            return
        if key in {262, curses.KEY_HOME if curses is not None else -1}:
            state.input.cursor = 0
            return
        if key in {360, curses.KEY_END if curses is not None else -1}:
            state.input.cursor = len(state.input.draft)
            return
        if key in {259, curses.KEY_UP if curses is not None else -1}:
            _history_recall(state, direction=1)
            return
        if key in {258, curses.KEY_DOWN if curses is not None else -1}:
            _history_recall(state, direction=-1)
            return
        if _is_printable_key(key):
            _insert_input_text(state, chr(key))
            return
        return
    if key in {ord("j"), ord("J"), curses.KEY_DOWN if curses is not None else -1}:
        if state.active_panel == "session":
            _move_left_selection(state, delta=1)
            return
        if state.active_panel == "detail":
            state.detail.offset += 1
        return
    if key in {ord("k"), ord("K"), curses.KEY_UP if curses is not None else -1}:
        if state.active_panel == "session":
            _move_left_selection(state, delta=-1)
            return
        if state.active_panel == "detail":
            state.detail.offset = max(0, state.detail.offset - 1)


def _resolve_storage_dir(state: InteractiveShellState) -> Path:
    storage_dir = getattr(state, "storage_dir", None)
    if storage_dir is not None:
        return Path(storage_dir)
    return load_config(state.workdir).storage_dir


def _resolve_navigation_context(
    state: InteractiveShellState,
    *,
    left_view: str,
    requested_session_index: int,
    requested_log_index: int,
) -> _TuiNavigationContext:
    resolved_left_view = left_view if left_view in {"sessions", "logs"} else "sessions"
    store = SessionStore(_resolve_storage_dir(state))
    sessions = store.list_sessions()
    if not sessions:
        return _TuiNavigationContext(
            left_view=resolved_left_view,
            sessions=[],
            selected_session=None,
            selected_session_index=0,
            selected_logs=[],
            selected_log_index=0,
        )
    resolved_session_index = max(0, min(requested_session_index, len(sessions) - 1))
    selected_session = sessions[resolved_session_index]
    selected_logs = store.read_log(selected_session.session_id)
    if not selected_logs:
        resolved_log_index = 0
    else:
        resolved_log_index = max(0, min(requested_log_index, len(selected_logs) - 1))
    return _TuiNavigationContext(
        left_view=resolved_left_view,
        sessions=sessions,
        selected_session=selected_session,
        selected_session_index=resolved_session_index,
        selected_logs=selected_logs,
        selected_log_index=resolved_log_index,
    )


def _left_session_lines(navigation: _TuiNavigationContext) -> list[str]:
    lines = ["view: sessions"]
    if not navigation.sessions:
        return [*lines, "no sessions"]
    start, end = _selection_window(
        navigation.selected_session_index,
        len(navigation.sessions),
        _LEFT_WINDOW_SIZE,
    )
    lines.append(f"sessions [{start + 1}:{end}]")
    for index in range(start, end):
        record = navigation.sessions[index]
        marker = ">" if index == navigation.selected_session_index else "-"
        lines.append(
            f"{marker} {record.session_id} {record.status} "
            f"{shorten(record.description, width=20, placeholder='...')}"
        )
    return lines


def _left_log_lines(navigation: _TuiNavigationContext) -> list[str]:
    session = navigation.selected_session
    session_id = session.session_id if session is not None else "none"
    lines = [f"view: logs ({session_id})"]
    if navigation.selected_session is None:
        return [*lines, "no sessions"]
    if not navigation.selected_logs:
        return [*lines, "no logs"]
    start, end = _selection_window(
        navigation.selected_log_index,
        len(navigation.selected_logs),
        _LEFT_WINDOW_SIZE,
    )
    lines.append(f"logs [{start + 1}:{end}]")
    for index in range(start, end):
        marker = ">" if index == navigation.selected_log_index else "-"
        lines.append(
            f"{marker} {index + 1}. "
            f"{shorten(navigation.selected_logs[index], width=34, placeholder='...')}"
        )
    return lines


def _session_summary_lines(
    session: SessionRecord | None,
    logs: list[str],
) -> tuple[list[str], int]:
    if session is None:
        return ["session summary: none"], 0
    lines = [
        "session summary:",
        f"session: {session.session_id}",
        f"status: {session.status}",
        f"mode: {session.mode}",
        f"risk: {session.risk_level}",
        f"created: {session.created_at}",
        f"workdir: {session.workdir}",
        f"description: {session.description}",
        f"commands: {len(session.commands)}",
        *(f"- {command}" for command in session.commands[:3]),
        f"logs: {len(logs)} lines",
    ]
    return lines, 0


def _log_context_lines(
    session: SessionRecord | None,
    logs: list[str],
    log_index: int,
) -> tuple[list[str], int]:
    if session is None:
        return ["log context: none"], 0
    if not logs:
        return [f"log context: {session.session_id}", "no logs"], 0
    start, end = _selection_window(log_index, len(logs), _DETAIL_WINDOW_SIZE)
    lines = [
        f"log context: {session.session_id}",
        f"log lines [{start + 1}:{end}]",
    ]
    for index in range(start, end):
        marker = ">" if index == log_index else "-"
        lines.append(f"{marker} {index + 1}. {logs[index]}")
    return lines, 0


def _selection_window(selection: int, total: int, window_size: int) -> tuple[int, int]:
    if total <= 0:
        return 0, 0
    if total <= window_size:
        return 0, total
    resolved_selection = max(0, min(selection, total - 1))
    start = max(0, min(resolved_selection - (window_size // 2), total - window_size))
    end = min(total, start + window_size)
    return start, end


def _move_left_selection(state: _TuiShellState, *, delta: int) -> None:
    if state.left.view == "logs":
        state.left.log_index = max(0, state.left.log_index + delta)
        return
    state.left.session_index = max(0, state.left.session_index + delta)


def _next_panel(current: str) -> str:
    panels = ["input", "session", "detail"]
    if current not in panels:
        return panels[0]
    next_index = (panels.index(current) + 1) % len(panels)
    return panels[next_index]


def _reset_input_history_navigation(state: _TuiShellState) -> None:
    state.input.history_index = None
    state.input.saved_draft = ""


def _history_recall(state: _TuiShellState, direction: int) -> None:
    history = state.input.history
    if not history:
        return
    if state.input.history_index is None:
        state.input.saved_draft = state.input.draft
        state.input.history_index = 0
    else:
        if direction < 0 and state.input.history_index == 0:
            state.input.history_index = None
            state.input.draft = state.input.saved_draft
            state.input.saved_draft = ""
            state.input.cursor = len(state.input.draft)
            return
        new_index = state.input.history_index + direction
        if new_index < 0:
            new_index = 0
        if new_index >= len(history):
            state.input.history_index = None
            state.input.draft = state.input.saved_draft
            state.input.saved_draft = ""
            state.input.cursor = len(state.input.draft)
            return
        state.input.history_index = new_index
    state.input.draft = history[state.input.history_index]
    state.input.cursor = len(state.input.draft)


def _insert_input_text(state: _TuiShellState, text: str) -> None:
    draft = state.input.draft
    cursor = max(0, min(state.input.cursor, len(draft)))
    state.input.draft = draft[:cursor] + text + draft[cursor:]
    state.input.cursor = cursor + len(text)
    _reset_input_history_navigation(state)


def _delete_input_before_cursor(state: _TuiShellState) -> None:
    draft = state.input.draft
    cursor = max(0, min(state.input.cursor, len(draft)))
    if cursor == 0:
        return
    state.input.draft = draft[: cursor - 1] + draft[cursor:]
    state.input.cursor = cursor - 1
    _reset_input_history_navigation(state)


def _move_input_cursor(state: _TuiShellState, delta: int) -> None:
    state.input.cursor = max(0, min(state.input.cursor + delta, len(state.input.draft)))



def _is_printable_key(key: int) -> bool:
    return 32 <= key <= 126 or key >= 0x4E00


def _submit_input_task(state: _TuiShellState) -> None:
    description = state.input.draft.strip()
    if not description:
        return
    state.input.busy = True
    state.input.last_submitted = description
    state.input.history.insert(0, description)
    state.input.history = state.input.history[:10]
    state.input.draft = ""
    state.input.cursor = 0
    _reset_input_history_navigation(state)
    state.session.pending_description = description
    state.session.pending_result = None
    try:
        result = run_task_session(
            description=description,
            workdir=state.workdir,
            mode=state.mode,
            storage_dir=state.storage_dir,
        )
    except Exception as exc:  # pragma: no cover - interactive guard
        state.last_shell_stderr = str(exc)
        state.input.busy = False
        return
    state.session.last_result = result
    if getattr(result.plan, "status", None) == "awaiting_confirmation":
        state.session.pending_result = result
    else:
        state.session.pending_description = None
    state.input.busy = False


def _panel_title(title: str, is_active: bool) -> str:
    if is_active:
        return f"{title} [active]"
    return title


def _left_panel_title(active_panel: str, left_view: str) -> str:
    title = f"LEFT // navigator [{left_view}]"
    if active_panel == "session":
        return f"{title} [active]"
    return title


def _detail_panel_title(active_panel: str, detail_view: str) -> str:
    title = f"RIGHT // detail [{detail_view}]"
    if active_panel == "detail":
        return f"{title} [active]"
    return title


def _format_planner_trace_line(item) -> str:
    line = f"attempt={item.attempt_index} source={item.source}"
    if item.note:
        return f"{line} note={item.note}"
    return line


def _latest_planner_source(result) -> str:
    if result is None:
        return "none"
    trace = getattr(result, "planner_trace", [])
    if not trace:
        return "none"
    latest = trace[-1]
    if latest.note:
        return f"{latest.source} ({latest.note})"
    return str(latest.source)


def _boxed(title: str, lines: list[str]) -> str:
    inner_width = _BOX_WIDTH
    prepared: list[str] = []
    for raw_line in lines:
        prepared.extend(wrap(str(raw_line), width=inner_width) or [""])
    top = f"┌─ {title} " + "─" * max(0, inner_width - len(title) - 1) + "┐"
    body = [f"│ {line.ljust(inner_width)} │" for line in prepared]
    bottom = "└" + ("─" * (inner_width + 2)) + "┘"
    return "\n".join([top, *body, bottom])
