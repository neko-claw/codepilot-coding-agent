"""Terminal dashboard rendering helpers for a Codex-like shell experience."""

from __future__ import annotations

from pathlib import Path
from textwrap import wrap
from typing import TYPE_CHECKING

from codepilot.runtime.session import _extract_failure_target_files

if TYPE_CHECKING:
    from codepilot.cli import InteractiveShellState
    from codepilot.runtime.session import TaskSessionResult


def render_shell_intro_panel(state: InteractiveShellState) -> str:
    """Render the shell intro as a compact dashboard panel."""
    lines = [
        "CodePilot // Agent Shell",
        f"workspace : {state.workdir}",
        f"mode      : {state.mode}",
        "goal      : 默认自动执行；/mode plan 可切回仅规划。",
        "examples  : /run 修复失败测试 | /mode plan | /exec pytest -q | "
        "/dashboard | /files src/**/*.py",
    ]
    return _boxed("CodePilot", lines)


def render_shell_status_panel(state: InteractiveShellState) -> str:
    """Render current shell state for /status or /dashboard."""
    pending = state.pending_description or "none"
    latest_session = getattr(getattr(state, "last_result", None), "session_id", "none")
    latest_failure = _latest_failure_type(getattr(state, "last_result", None))
    latest_planner = _latest_planner_source(getattr(state, "last_result", None))
    task_draft = getattr(state, "task_draft", "") or "none"
    recent_tasks = getattr(state, "recent_tasks", [])
    lines = [
        f"workspace       : {state.workdir}",
        f"mode            : {state.mode}",
        f"shell_session   : {state.shell_session_id or 'none'}",
        f"shell_cwd       : {state.shell_cwd or state.workdir}",
        f"pending_plan    : {pending}",
        f"task_draft      : {task_draft}",
        f"recent_tasks    : {len(recent_tasks)}",
        f"latest_session  : {latest_session}",
        f"latest_failure  : {latest_failure}",
        f"latest_planner  : {latest_planner}",
    ]
    if state.last_shell_command:
        lines.append(f"last_shell_cmd  : {state.last_shell_command}")
    if state.last_shell_exit_code is not None:
        lines.append(f"last_shell_exit : {state.last_shell_exit_code}")
    pending_result = getattr(state, "pending_result", None)
    if pending_result is not None:
        commands = getattr(pending_result.plan, "candidate_commands", [])
        if commands:
            lines.append(f"pending_commands: {', '.join(commands)}")
    return _boxed("Shell Status", lines)


def render_session_dashboard(result: TaskSessionResult) -> str:
    """Render the latest session as a compact terminal dashboard."""
    summary_lines = [
        f"session_id : {result.session_id}",
        f"status     : {result.plan.status}",
        f"next_action: {result.plan.next_action}",
        f"planner    : {_latest_planner_source(result)}",
        f"risk       : {result.plan.risk.level} ({result.plan.risk.reason})",
        f"summary    : {result.plan.summary}",
    ]
    execution_budget = getattr(result, "execution_budget", None)
    if execution_budget is not None:
        summary_lines.extend(
            [
                (
                    f"cmd_budget : {execution_budget.command_used}/"
                    f"{execution_budget.command_limit} "
                    f"exhausted={execution_budget.command_exhausted}"
                ),
                (
                    f"edit_budget: {execution_budget.edit_used}/"
                    f"{execution_budget.edit_limit} "
                    f"exhausted={execution_budget.edit_exhausted}"
                ),
            ]
        )
        if execution_budget.stop_reason:
            summary_lines.append(f"budget_stop: {execution_budget.stop_reason}")
    sections = [_boxed("Latest Session", summary_lines)]

    if result.plan.steps:
        plan_steps = [f"[{index}] {step}" for index, step in enumerate(result.plan.steps, start=1)]
        sections.append(_boxed("Plan Steps", plan_steps))
    if result.plan.candidate_files:
        candidate_files = [
            _relative_or_raw(path, result) for path in result.plan.candidate_files[:6]
        ]
        sections.append(_boxed("Candidate Files", candidate_files))
    if result.inspected_files:
        inspected_files = [_relative_or_raw(path, result) for path in result.inspected_files[:6]]
        sections.append(_boxed("Inspected Files", inspected_files))
    if result.plan.candidate_commands:
        sections.append(_boxed("Candidate Commands", result.plan.candidate_commands[:6]))
    planner_trace = getattr(result, "planner_trace", [])
    if planner_trace:
        sections.append(
            _boxed(
                "Planner Trace",
                [
                    (
                        f"attempt={attempt.attempt_index} source={attempt.source}"
                        + (f" note={attempt.note}" if attempt.note else "")
                    )
                    for attempt in planner_trace
                ],
            )
        )
    retry_trace = getattr(result, "retry_trace", [])
    if retry_trace:
        sections.append(
            _boxed(
                "Retry Trace",
                [
                    (
                        f"attempt={attempt.attempt_index} failure={attempt.failure_type} "
                        f"retried={attempt.retried} reason={attempt.reason}"
                    )
                    for attempt in retry_trace
                ],
            )
        )
    if result.failure_hints:
        sections.append(_boxed("Failure Hints", result.failure_hints[:6]))
    failure_targets = _failure_target_files(result)
    if failure_targets:
        sections.append(_boxed("Failure Targets", failure_targets[:6]))
    return "\n\n".join(sections)


def render_dashboard_snapshot(state: InteractiveShellState) -> str:
    """Render a combined shell + latest-session dashboard."""
    sections = [render_shell_status_panel(state)]
    last_result = getattr(state, "last_result", None)
    if last_result is not None:
        sections.append(render_session_dashboard(last_result))
    return "\n\n".join(sections)


def _latest_failure_type(result: TaskSessionResult | None) -> str:
    if result is None:
        return "none"
    retry_trace = getattr(result, "retry_trace", [])
    if not retry_trace:
        return "none"
    return retry_trace[-1].failure_type


def _latest_planner_source(result: TaskSessionResult | None) -> str:
    if result is None:
        return "none"
    planner_trace = getattr(result, "planner_trace", [])
    if not planner_trace:
        return "none"
    latest = planner_trace[-1]
    if latest.note:
        return f"{latest.source} ({latest.note})"
    return latest.source


def _failure_target_files(result: TaskSessionResult) -> list[str]:
    command_results = list(getattr(result, "command_results", []))
    edit_results = list(getattr(result, "edit_results", []))
    workdir = Path(getattr(getattr(result, "request", None), "workdir", ".")).resolve()
    return _extract_failure_target_files(command_results, edit_results, workdir)


def _relative_or_raw(path: str, result: TaskSessionResult) -> str:
    request = getattr(result, "request", None)
    workdir_value = getattr(request, "workdir", None)
    if workdir_value is None:
        return str(path)
    workdir = Path(workdir_value).resolve()
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(workdir))
    except ValueError:
        return str(candidate)


def _boxed(title: str, lines: list[str], *, width: int = 94) -> str:
    inner_width = max(20, width - 4)
    prepared: list[str] = []
    for raw_line in lines:
        wrapped = wrap(raw_line, width=inner_width) or [""]
        prepared.extend(wrapped)
    top = f"┌─ {title} " + "─" * max(0, inner_width - len(title) - 1) + "┐"
    body = [f"│ {line.ljust(inner_width)} │" for line in prepared]
    bottom = f"└{'─' * (inner_width + 2)}┘"
    return "\n".join([top, *body, bottom])
