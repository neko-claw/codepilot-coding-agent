"""CLI entrypoint for CodePilot."""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

try:
    import readline
except ImportError:  # pragma: no cover - platform-dependent
    readline = None  # type: ignore[assignment]

from codepilot.core.config import CodePilotConfig, load_config
from codepilot.eval import (
    load_benchmark_cases,
    run_benchmark_suite,
    run_swebench_suite,
    supported_dataset_formats,
)
from codepilot.executor.shell import PersistentShellSession
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
    run_harness_session,
    run_harness_suite,
)
from codepilot.integrations.deepseek import DeepSeekPlannerClient
from codepilot.runtime.session import TaskSessionResult, run_task_session
from codepilot.storage.session_store import SessionStore, WorkspaceSnapshotManager
from codepilot.tools.filesystem import edit_file_by_replacement, read_file_with_line_numbers
from codepilot.tools.search import glob_search, grep_search
from codepilot.ui.dashboard import (
    render_dashboard_snapshot,
    render_session_dashboard,
    render_shell_intro_panel,
    render_shell_status_panel,
)
from codepilot.ui.tui import run_tui_shell

_INTERACTIVE_HELP = """可用命令:
  直接输入需求         默认 auto 模式下直接改代码并验证；plan 模式下生成待确认计划
  /plan <需求>         显式生成计划，不执行副作用命令
  /run <需求>          立即以 auto 模式执行任务（允许自动改代码 + 验证）
  /approve             执行当前待确认计划
  /cancel              清除当前待确认计划
  /status              查看当前 shell 状态
  /dashboard           查看 Codex 风格的当前仪表板
  /mode <plan|auto>    切换默认模式
  /workdir <路径>      切换工作目录
  /cd <路径>           切换 shell 当前目录
  /exec <命令>         在持久 shell 会话中执行任意命令
  /files [glob]        查看匹配文件
  /grep <regex> [glob] 搜索文件内容
  /read <path> [行范围] 按行读取文件，例如 /read src/app.py 1:40
  /replace <path> <old> <new>  做确定性替换并返回 diff + 语法检查
  /history             查看历史会话
  /logs <session_id>   查看会话日志
  /restore <snapshot>  恢复工作区快照
  @<session_id>        等价于 /logs <session_id>
  @<snapshot_id>       等价于 /restore <snapshot_id>
  /help                查看帮助
  /exit                退出
"""
_HISTORY_FILENAME = "cli-history.txt"
_HISTORY_LENGTH = 200


@dataclass(slots=True)
class InteractiveShellState:
    """Mutable state for the interactive CLI shell."""

    workdir: Path
    mode: str = "auto"
    active_panel: str = "input"
    pending_description: str | None = None
    pending_result: TaskSessionResult | None = None
    last_result: TaskSessionResult | None = None
    shell_session_id: str = ""
    shell_cwd: Path | None = None
    last_shell_command: str | None = None
    last_shell_exit_code: int | None = None
    last_shell_stdout: str | None = None
    last_shell_stderr: str | None = None
    task_draft: str = ""
    recent_tasks: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ShellResources:
    """Resolved resources bound to the current workdir."""

    config: CodePilotConfig
    store: SessionStore
    snapshot_manager: WorkspaceSnapshotManager
    shell_session: PersistentShellSession


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="codepilot")
    parser.add_argument("--tui", action="store_true", help="Launch the curses-style TUI shell")
    parser.add_argument("--workdir", default=".", help="Workspace for interactive shell or TUI")
    subparsers = parser.add_subparsers(dest="command", required=False)

    run_parser = subparsers.add_parser("run", help="Run a CodePilot session")
    run_parser.add_argument("description", help="Natural-language task description")
    run_parser.add_argument("--workdir", default=".")
    run_parser.add_argument("--mode", choices=("plan", "auto"), default="plan")
    run_parser.add_argument("--max-commands", type=int, default=None)
    run_parser.add_argument("--max-edits", type=int, default=None)

    history_parser = subparsers.add_parser("history", help="List previous sessions")
    history_parser.add_argument("--workdir", default=".")

    logs_parser = subparsers.add_parser("logs", help="Show session logs")
    logs_parser.add_argument("session_id")
    logs_parser.add_argument("--workdir", default=".")

    benchmark_parser = subparsers.add_parser("eval", help="Run benchmark suites against a planner")
    benchmark_parser.add_argument("suite", help="Path to a benchmark fixture or dataset export")
    benchmark_parser.add_argument(
        "--dataset-format",
        default="auto",
        choices=("auto", *supported_dataset_formats()),
        help="Dataset format override",
    )
    benchmark_parser.add_argument("--workdir", default=".")
    benchmark_parser.add_argument(
        "--source-repo", default=None, help="Source repository for SWE-bench tasks"
    )
    benchmark_parser.add_argument(
        "--checkout-ref", default=None, help="Git ref or commit to checkout for SWE-bench tasks"
    )

    harness_parser = subparsers.add_parser("harness", help="Developer-day harness for daily use")
    harness_subparsers = harness_parser.add_subparsers(dest="harness_command", required=False)

    harness_run_parser = harness_subparsers.add_parser(
        "run", help="Run a single task through the harness"
    )
    harness_run_parser.add_argument("description", help="Natural-language task description")
    harness_run_parser.add_argument("--workdir", default=".")
    harness_run_parser.add_argument("--mode", choices=("plan", "auto"), default="auto")
    harness_run_parser.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help="Harness report format",
    )
    harness_run_parser.add_argument("--max-auto-retries", type=int, default=1)
    harness_run_parser.add_argument("--max-commands", type=int, default=None)
    harness_run_parser.add_argument("--max-edits", type=int, default=None)
    harness_run_parser.add_argument(
        "--command-allowlist",
        action="append",
        default=[],
        help="Optional allowlisted verification commands; repeat for multiple entries",
    )
    harness_run_parser.add_argument("--strict-command-allowlist", action="store_true")

    harness_eval_parser = harness_subparsers.add_parser(
        "eval", help="Run a benchmark suite through the harness"
    )
    harness_eval_parser.add_argument("suite", help="Path to a benchmark fixture or dataset export")
    harness_eval_parser.add_argument(
        "--dataset-format",
        default="auto",
        choices=("auto", *supported_dataset_formats()),
        help="Dataset format override",
    )
    harness_eval_parser.add_argument("--workdir", default=".")
    harness_eval_parser.add_argument(
        "--source-repo", default=None, help="Source repository for SWE-bench tasks"
    )
    harness_eval_parser.add_argument(
        "--checkout-ref", default=None, help="Git ref or commit to checkout for SWE-bench tasks"
    )
    harness_eval_parser.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help="Harness report format",
    )

    harness_resume_parser = harness_subparsers.add_parser(
        "resume", help="Resume a previously recorded harness session"
    )
    harness_resume_parser.add_argument("session_id", help="Session identifier to resume")
    harness_resume_parser.add_argument(
        "--mode",
        choices=("plan", "auto"),
        default=None,
        help="Override the stored mode when resuming",
    )
    harness_resume_parser.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help="Harness report format",
    )
    harness_resume_parser.add_argument("--max-auto-retries", type=int, default=1)
    harness_resume_parser.add_argument("--max-commands", type=int, default=None)
    harness_resume_parser.add_argument("--max-edits", type=int, default=None)
    harness_resume_parser.add_argument("--strict-command-allowlist", action="store_true")

    harness_loop_parser = harness_subparsers.add_parser(
        "loop", help="Run repeated closed-loop harness rounds until success"
    )
    harness_loop_parser.add_argument("description", help="Natural-language task description")
    harness_loop_parser.add_argument("--workdir", default=".")
    harness_loop_parser.add_argument("--mode", choices=("auto",), default="auto")
    harness_loop_parser.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help="Harness report format",
    )
    harness_loop_parser.add_argument("--max-rounds", type=int, default=3)
    harness_loop_parser.add_argument("--max-auto-retries", type=int, default=1)
    harness_loop_parser.add_argument("--max-commands", type=int, default=None)
    harness_loop_parser.add_argument("--max-edits", type=int, default=None)
    harness_loop_parser.add_argument(
        "--command-allowlist",
        action="append",
        default=[],
        help="Optional allowlisted verification commands; repeat for multiple entries",
    )
    harness_loop_parser.add_argument("--strict-command-allowlist", action="store_true")

    harness_subparsers.add_parser("shell", help="Open the interactive shell")

    restore_parser = subparsers.add_parser("restore", help="Restore a workspace snapshot")
    restore_parser.add_argument("snapshot_id")
    restore_parser.add_argument("--workdir", default=".")

    return parser


def _build_planner_client(config: CodePilotConfig) -> DeepSeekPlannerClient | None:
    if not config.deepseek_enabled:
        return None
    return DeepSeekPlannerClient(
        api_key=config.deepseek_api_key or "",
        base_url=config.deepseek_base_url,
        model=config.deepseek_model,
        timeout=config.deepseek_timeout,
        retries=config.deepseek_retries,
    )


def _write(output_stream: TextIO, text: str) -> None:
    output_stream.write(f"{text}\n")
    output_stream.flush()


def _print_result_paths(title: str, paths: list[str], output_stream: TextIO) -> None:
    if not paths:
        return
    _write(output_stream, title)
    for path in paths:
        _write(output_stream, f"- {path}")


def _print_edit_results(result: TaskSessionResult, output_stream: TextIO) -> None:
    if not result.edit_results:
        return
    _write(output_stream, "edit_results:")
    for edit_result in result.edit_results:
        summary = (
            f"- {edit_result.path} applied={edit_result.applied} "
            f"reverted={edit_result.reverted} syntax={edit_result.syntax_check}"
        )
        _write(output_stream, summary)
        for diff_line in edit_result.diff:
            _write(output_stream, f"  {diff_line}")


def _print_session_result(result: TaskSessionResult, output_stream: TextIO) -> None:
    _write(output_stream, render_session_dashboard(result))
    _write(output_stream, f"session_id: {result.session_id}")
    _write(output_stream, f"status: {result.plan.status}")
    _write(output_stream, f"next_action: {result.plan.next_action}")
    _write(output_stream, f"summary: {result.plan.summary}")
    _write(output_stream, "steps:")
    for step in result.plan.steps:
        _write(output_stream, f"- {step}")
    _print_result_paths("candidate_files:", result.plan.candidate_files, output_stream)
    _print_result_paths("inspected_files:", result.inspected_files, output_stream)
    _write(output_stream, "candidate_commands:")
    for command in result.plan.candidate_commands:
        _write(output_stream, f"- {command}")
    _write(output_stream, f"risk: {result.plan.risk.level} ({result.plan.risk.reason})")
    _write(output_stream, f"user_options: {', '.join(result.plan.user_options)}")
    if result.github_snapshot is not None:
        _write(output_stream, f"github: {result.github_snapshot.full_name}")
    _print_edit_results(result, output_stream)
    for command_result in result.command_results:
        _write(output_stream, f"command: {command_result.command} => {command_result.exit_code}")
    retry_trace = getattr(result, "retry_trace", [])
    planner_trace = getattr(result, "planner_trace", [])
    if planner_trace:
        _write(output_stream, "planner_trace:")
        for attempt in planner_trace:
            note = f" note={attempt.note}" if attempt.note else ""
            _write(
                output_stream,
                f"- attempt={attempt.attempt_index} source={attempt.source}{note}",
            )
    if retry_trace:
        _write(output_stream, "retry_trace:")
        for attempt in retry_trace:
            _write(
                output_stream,
                "- "
                f"attempt={attempt.attempt_index} failure={attempt.failure_type} "
                f"retried={attempt.retried} reason={attempt.reason}",
            )
    if result.failure_hints:
        _write(output_stream, "failure_hints:")
        for hint in result.failure_hints:
            _write(output_stream, f"- {hint}")
    if result.rollback_snapshot_id:
        _write(output_stream, f"rollback_snapshot: {result.rollback_snapshot_id}")


def _print_benchmark_suite_result(result, output_stream: TextIO) -> None:
    benchmark_result = getattr(result, "benchmark_result", result)
    _write(output_stream, f"benchmark_total: {benchmark_result.total}")
    _write(output_stream, f"benchmark_passed: {benchmark_result.passed}")
    _write(output_stream, f"benchmark_failed: {benchmark_result.failed}")
    for case_result in benchmark_result.case_results:
        _write(
            output_stream,
            f"- {case_result.case.name} passed={case_result.passed} "
            f"failures={'; '.join(case_result.failures) if case_result.failures else 'none'}",
        )


def _print_harness_report(
    result: TaskSessionResult, output_stream: TextIO, output_format: str
) -> None:
    if output_format == "json":
        _write(output_stream, format_harness_json(result))
        return
    if output_format == "markdown":
        _write(output_stream, format_harness_markdown(result))
        return
    _write(output_stream, format_harness_text(result))


def _print_harness_suite_report(result, output_stream: TextIO, output_format: str) -> None:
    if output_format == "json":
        _write(output_stream, format_suite_json(result))
        return
    if output_format == "markdown":
        _write(output_stream, format_suite_markdown(result))
        return
    _write(output_stream, format_suite_text(result))


def _print_harness_loop_report(result, output_stream: TextIO, output_format: str) -> None:
    if output_format == "json":
        _write(output_stream, format_loop_json(result))
        return
    if output_format == "markdown":
        _write(output_stream, format_loop_markdown(result))
        return
    _write(output_stream, format_loop_text(result))


def _print_history(store: SessionStore, output_stream: TextIO) -> None:
    for record in store.list_sessions():
        _write(output_stream, f"{record.session_id}\t{record.status}\t{record.description}")


def _print_logs(store: SessionStore, session_id: str, output_stream: TextIO) -> None:
    for line in store.read_log(session_id):
        _write(output_stream, line)


def _restore_snapshot(
    snapshot_manager: WorkspaceSnapshotManager,
    snapshot_id: str,
    output_stream: TextIO,
) -> None:
    restored_files = snapshot_manager.restore_snapshot(snapshot_id)
    _write(output_stream, f"restored {len(restored_files)} files")
    for path in restored_files:
        _write(output_stream, str(path))


def render_shell_intro(state: InteractiveShellState) -> str:
    """Render a more natural shell introduction similar to agent-style CLIs."""
    return render_shell_intro_panel(state)


def _shell_prompt(state: InteractiveShellState) -> str:
    pending = "*" if state.pending_description else ""
    return f"codepilot[{state.mode}{pending}] {state.workdir}> "


def build_completion_candidates(
    state: InteractiveShellState,
    *,
    store: SessionStore,
    snapshot_manager: WorkspaceSnapshotManager,
) -> list[str]:
    """Build completion candidates for slash commands, sessions, and snapshots."""
    base_commands = [
        "/help",
        "/exit",
        "/history",
        "/status",
        "/dashboard",
        "/approve",
        "/cancel",
        "/mode auto",
        "/mode plan",
        "/plan ",
        "/run ",
        "/files ",
        "/grep ",
        "/read ",
        "/replace ",
        "/cd ",
        "/exec ",
        "/logs ",
        "/restore ",
        f"/workdir {state.workdir}",
    ]
    session_entries = [f"@{record.session_id}" for record in store.list_sessions()]
    snapshots_dir = getattr(snapshot_manager, "snapshots_dir", None)
    snapshot_entries: list[str] = []
    if snapshots_dir is not None:
        snapshot_entries = [
            f"@{path.name}"
            for path in sorted(Path(snapshots_dir).glob("snapshot-*"), reverse=True)
            if path.is_dir()
        ]
    return sorted(set(base_commands + session_entries + snapshot_entries))


def _make_shell_completer(candidates: list[str]):
    def _completer(text: str, state_index: int) -> str | None:
        matches = [candidate for candidate in candidates if candidate.startswith(text)]
        if state_index >= len(matches):
            return None
        return matches[state_index]

    return _completer


def _history_path(storage_dir: str | Path) -> Path:
    return Path(storage_dir) / _HISTORY_FILENAME


def configure_shell_readline(
    state: InteractiveShellState,
    *,
    storage_dir: str | Path,
    readline_backend: Any | None = None,
    store: SessionStore,
    snapshot_manager: WorkspaceSnapshotManager,
) -> Path | None:
    """Configure readline completion and persistent history for the shell."""
    backend = readline_backend if readline_backend is not None else readline
    if backend is None:
        return None
    history_path = _history_path(storage_dir)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.touch(exist_ok=True)
    candidates = build_completion_candidates(
        state,
        store=store,
        snapshot_manager=snapshot_manager,
    )
    backend.parse_and_bind("tab: complete")
    backend.set_completer(_make_shell_completer(candidates))
    backend.set_history_length(_HISTORY_LENGTH)
    try:
        backend.read_history_file(str(history_path))
    except OSError:
        pass
    return history_path


def _persist_shell_history(readline_backend: Any | None, history_path: Path | None) -> None:
    if readline_backend is None or history_path is None:
        return
    try:
        readline_backend.write_history_file(str(history_path))
    except OSError:
        pass


def _print_shell_banner(output_stream: TextIO, state: InteractiveShellState) -> None:
    _write(output_stream, render_shell_intro(state))


def _handle_shell_meta_command(
    line: str,
    state: InteractiveShellState,
    output_stream: TextIO,
) -> int | None:
    if line in {"/exit", "/quit"}:
        _write(output_stream, "bye")
        return 0
    if line in {"/help", "/?"}:
        _write(output_stream, _INTERACTIVE_HELP.rstrip())
        return 1
    if line.startswith("/mode "):
        requested_mode = line.split(maxsplit=1)[1].strip()
        if requested_mode not in {"plan", "auto"}:
            _write(output_stream, "mode 仅支持 plan 或 auto")
            return 1
        state.mode = requested_mode
        _write(output_stream, f"mode => {state.mode}")
        return 1
    if line.startswith("/workdir "):
        state.workdir = Path(line.split(maxsplit=1)[1].strip()).expanduser().resolve()
        state.shell_cwd = state.workdir
        state.pending_description = None
        state.pending_result = None
        _write(output_stream, f"workdir => {state.workdir}")
        return 2
    return None


def _build_shell_resources(state: InteractiveShellState) -> ShellResources:
    config = load_config(state.workdir)
    return ShellResources(
        config=config,
        store=SessionStore(config.storage_dir),
        snapshot_manager=WorkspaceSnapshotManager(config.storage_dir),
        shell_session=PersistentShellSession(workdir=state.workdir),
    )


def _print_shell_status(state: InteractiveShellState, output_stream: TextIO) -> None:
    _write(output_stream, render_shell_status_panel(state))


def _parse_read_range(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    if not re.fullmatch(r"\d+:\d+", value):
        raise ValueError("行范围必须是 start:end")
    start_text, end_text = value.split(":", maxsplit=1)
    return int(start_text), int(end_text)


def _handle_workspace_command(  # pylint: disable=too-many-return-statements
    line: str,
    state: InteractiveShellState,
    resources: ShellResources,
    output_stream: TextIO,
) -> int | None:
    args = shlex.split(line)
    if not args:
        return None
    command = args[0]
    if command == "/files":
        pattern = args[1] if len(args) > 1 else "**/*"
        for path in glob_search(state.workdir, pattern, limit=50):
            _write(output_stream, path)
        return 1
    if command == "/grep":
        if len(args) < 2:
            _write(output_stream, "用法: /grep <regex> [glob]")
            return 1
        pattern = args[1]
        file_glob = args[2] if len(args) > 2 else "**/*"
        for match in grep_search(state.workdir, pattern, file_glob=file_glob, limit=50):
            path = Path(match["path"]).resolve().relative_to(state.workdir)
            _write(output_stream, f"{path}:{match['line']}: {match['content']}")
        return 1
    if command == "/read":
        if len(args) < 2:
            _write(output_stream, "用法: /read <path> [start:end]")
            return 1
        target = (state.workdir / args[1]).resolve()
        start_line, end_line = _parse_read_range(args[2] if len(args) > 2 else None)
        result = read_file_with_line_numbers(target, start_line=start_line, end_line=end_line)
        for line_text in result.content:
            _write(output_stream, line_text)
        return 1
    if command == "/replace":
        if len(args) < 4:
            _write(output_stream, "用法: /replace <path> <old> <new>")
            return 1
        target = (state.workdir / args[1]).resolve()
        result = edit_file_by_replacement(target, args[2], args[3])
        _write(output_stream, f"syntax_check: {result.syntax_check}")
        for diff_line in result.diff:
            _write(output_stream, diff_line)
        return 1
    if command == "/cd":
        if len(args) < 2:
            _write(output_stream, "用法: /cd <path>")
            return 1
        target = Path(args[1]).expanduser()
        if not target.is_absolute():
            target = (resources.shell_session.cwd / target).resolve()
        if not target.exists() or not target.is_dir():
            _write(output_stream, f"error: {target} does not exist or is not a directory")
            return 1
        resources.shell_session.cwd = target.resolve()
        state.workdir = resources.shell_session.cwd
        state.shell_cwd = state.workdir
        state.pending_description = None
        state.pending_result = None
        _write(output_stream, f"cwd => {state.workdir}")
        return 2
    if command == "/exec":
        command_text = line[len("/exec") :].strip()
        if not command_text:
            _write(output_stream, "用法: /exec <shell command>")
            return 1
        before_cwd = resources.shell_session.cwd
        result = resources.shell_session.run(command_text)
        state.last_shell_command = command_text
        state.last_shell_exit_code = result.exit_code
        state.last_shell_stdout = result.stdout
        state.last_shell_stderr = result.stderr
        if state.shell_session_id:
            resources.store.append_log(state.shell_session_id, f"> /exec {command_text}")
            resources.store.append_log(
                state.shell_session_id, f"exit={result.exit_code} cwd={resources.shell_session.cwd}"
            )
        _write(output_stream, f"command: {result.command}")
        _write(output_stream, f"cwd: {resources.shell_session.cwd}")
        _write(output_stream, f"exit_code: {result.exit_code}")
        if result.stdout:
            _write(output_stream, "stdout:")
            for line_text in result.stdout.splitlines():
                _write(output_stream, f"  {line_text}")
        if result.stderr:
            _write(output_stream, "stderr:")
            for line_text in result.stderr.splitlines():
                _write(output_stream, f"  {line_text}")
        if resources.shell_session.cwd != before_cwd:
            state.workdir = resources.shell_session.cwd
            state.shell_cwd = state.workdir
            state.pending_description = None
            state.pending_result = None
            return 2
        return 1
    return None


def _handle_shell_storage_command(
    line: str,
    resources: ShellResources,
    output_stream: TextIO,
) -> int | None:
    if line == "/history":
        _print_history(resources.store, output_stream)
        return 1
    if line.startswith("/logs "):
        _print_logs(resources.store, line.split(maxsplit=1)[1].strip(), output_stream)
        return 1
    if line.startswith("/restore "):
        snapshot_id = line.split(maxsplit=1)[1].strip()
        _restore_snapshot(resources.snapshot_manager, snapshot_id, output_stream)
        return 1
    if line.startswith("@"):
        alias_value = line[1:].strip()
        if alias_value.startswith("snapshot-"):
            _restore_snapshot(resources.snapshot_manager, alias_value, output_stream)
        else:
            _print_logs(resources.store, alias_value, output_stream)
        return 1
    return None


def _run_shell_task(
    description: str,
    *,
    mode: str,
    state: InteractiveShellState,
    resources: ShellResources,
    output_stream: TextIO,
) -> TaskSessionResult:
    result = run_task_session(
        description=description,
        workdir=state.workdir,
        mode=mode,
        planner_client=_build_planner_client(resources.config),
        storage_dir=resources.config.storage_dir,
    )
    _print_session_result(result, output_stream)
    return result


def _resolve_task_request(  # pylint: disable=too-many-return-statements
    line: str,
    state: InteractiveShellState,
    output_stream: TextIO,
) -> tuple[str, str] | None:
    if line == "/approve":
        if state.pending_description is None:
            _write(output_stream, "当前没有待确认计划")
            return None
        return "auto", state.pending_description
    if line == "/cancel":
        state.pending_description = None
        state.pending_result = None
        _write(output_stream, "pending plan cleared")
        return None
    if line.startswith("/plan "):
        return "plan", line.split(maxsplit=1)[1].strip()
    if line.startswith("/run "):
        return "auto", line.split(maxsplit=1)[1].strip()
    if line.startswith("/"):
        _write(output_stream, "未知命令，输入 /help 查看可用操作")
        return None
    return state.mode, line


def _handle_shell_runtime_command(
    line: str,
    state: InteractiveShellState,
    resources: ShellResources,
    output_stream: TextIO,
) -> int | None:
    if line == "/status":
        _print_shell_status(state, output_stream)
        return 1
    if line == "/dashboard":
        _write(output_stream, render_dashboard_snapshot(state))
        return 1
    storage_status = _handle_shell_storage_command(line, resources, output_stream)
    if storage_status is not None:
        return storage_status
    workspace_status = _handle_workspace_command(line, state, resources, output_stream)
    if workspace_status is not None:
        return workspace_status
    resolved_request = _resolve_task_request(line, state, output_stream)
    if resolved_request is None:
        return 1
    resolved_mode, description = resolved_request
    result = _run_shell_task(
        description,
        mode=resolved_mode,
        state=state,
        resources=resources,
        output_stream=output_stream,
    )
    state.last_result = result
    if resolved_mode == "plan":
        state.pending_description = description
        state.pending_result = result
        _write(output_stream, "继续讨论计划 /approve 执行 /cancel 取消")
    else:
        state.pending_description = None
        state.pending_result = None
    return 1


def run_interactive_shell(
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    initial_workdir: str | Path | None = None,
    initial_mode: str = "auto",
) -> int:
    """Run an interactive CodePilot shell with slash-command shortcuts."""
    current_input = input_stream or sys.stdin
    current_output = output_stream or sys.stdout
    state = InteractiveShellState(
        workdir=Path(initial_workdir or Path.cwd()).resolve(),
        mode=initial_mode,
        shell_session_id=f"shell-{uuid4().hex[:12]}",
        shell_cwd=Path(initial_workdir or Path.cwd()).resolve(),
    )
    resources = _build_shell_resources(state)
    history_path = configure_shell_readline(
        state,
        storage_dir=resources.config.storage_dir,
        readline_backend=readline,
        store=resources.store,
        snapshot_manager=resources.snapshot_manager,
    )

    _print_shell_banner(current_output, state)
    _write(current_output, f"session => {state.shell_session_id}")

    while True:
        current_output.write(_shell_prompt(state))
        current_output.flush()
        raw_line = current_input.readline()
        if not raw_line:
            _write(current_output, "")
            _persist_shell_history(readline, history_path)
            return 0
        line = raw_line.strip()
        if not line:
            continue
        if readline is not None:
            readline.add_history(line)
        if state.shell_session_id:
            resources.store.append_log(state.shell_session_id, f"> {line}")
        shell_status = _handle_shell_meta_command(line, state, current_output)
        if shell_status is not None:
            if shell_status == 0:
                _persist_shell_history(readline, history_path)
                return 0
            if shell_status == 2:
                _persist_shell_history(readline, history_path)
                resources = _build_shell_resources(state)
                history_path = configure_shell_readline(
                    state,
                    storage_dir=resources.config.storage_dir,
                    readline_backend=readline,
                    store=resources.store,
                    snapshot_manager=resources.snapshot_manager,
                )
            continue
        try:
            runtime_status = _handle_shell_runtime_command(line, state, resources, current_output)
            if runtime_status == 2:
                _persist_shell_history(readline, history_path)
                resources = _build_shell_resources(state)
                history_path = configure_shell_readline(
                    state,
                    storage_dir=resources.config.storage_dir,
                    readline_backend=readline,
                    store=resources.store,
                    snapshot_manager=resources.snapshot_manager,
                )
        except (FileNotFoundError, ValueError, OSError, re.error) as exc:
            _write(current_output, f"error: {exc}")


def _run_subcommand(args: argparse.Namespace, workdir: Path) -> int:
    config = load_config(workdir)
    if args.command == "run":
        result = run_task_session(
            description=args.description,
            workdir=workdir,
            mode=args.mode,
            planner_client=_build_planner_client(config),
            storage_dir=config.storage_dir,
            max_command_results=args.max_commands,
            max_edit_results=args.max_edits,
        )
        _print_session_result(result, sys.stdout)
        return 0
    if args.command == "history":
        _print_history(SessionStore(config.storage_dir), sys.stdout)
        return 0
    if args.command == "logs":
        _print_logs(SessionStore(config.storage_dir), args.session_id, sys.stdout)
        return 0
    if args.command == "eval":
        planner_client = _build_planner_client(config)
        if planner_client is None:
            _write(sys.stdout, "error: DeepSeek planner is disabled; set DEEPSEEK_API_KEY first")
            return 2
        cases = load_benchmark_cases(args.suite)
        if args.dataset_format == "swebench":
            suite_result = run_swebench_suite(
                cases,
                planner_client,
                source_repo=args.source_repo,
                checkout_ref=args.checkout_ref,
            )
        else:
            suite_result = run_benchmark_suite(cases, planner_client)
        _print_benchmark_suite_result(suite_result, sys.stdout)
        return 0
    if args.command == "harness":
        if args.harness_command in (None, "shell"):
            return run_interactive_shell(initial_workdir=workdir)
        planner_client = _build_planner_client(config)
        if args.harness_command == "run":
            result = run_harness_session(
                description=args.description,
                workdir=workdir,
                mode=args.mode,
                planner_client=planner_client,
                command_allowlist=tuple(args.command_allowlist) or None,
                strict_command_allowlist=args.strict_command_allowlist,
                storage_dir=config.storage_dir,
                max_auto_retries=args.max_auto_retries,
                max_command_results=args.max_commands,
                max_edit_results=args.max_edits,
            )
            _print_harness_report(result, sys.stdout, args.format)
            return 0
        if args.harness_command == "resume":
            try:
                result = resume_harness_session(
                    args.session_id,
                    storage_dir=config.storage_dir,
                    planner_client=planner_client,
                    mode=args.mode,
                    max_auto_retries=args.max_auto_retries,
                    max_command_results=args.max_commands,
                    max_edit_results=args.max_edits,
                    strict_command_allowlist=args.strict_command_allowlist,
                )
            except FileNotFoundError:
                _write(sys.stdout, f"error: session not found: {args.session_id}")
                return 2
            _print_harness_report(result, sys.stdout, args.format)
            return 0
        if args.harness_command == "loop":
            result = run_harness_loop(
                description=args.description,
                workdir=workdir,
                planner_client=planner_client,
                mode=args.mode,
                max_rounds=args.max_rounds,
                command_allowlist=tuple(args.command_allowlist) or None,
                strict_command_allowlist=args.strict_command_allowlist,
                storage_dir=config.storage_dir,
                max_auto_retries=args.max_auto_retries,
                max_command_results=args.max_commands,
                max_edit_results=args.max_edits,
            )
            _print_harness_loop_report(result, sys.stdout, args.format)
            return 0
        if args.harness_command == "eval":
            if planner_client is None:
                _write(
                    sys.stdout, "error: DeepSeek planner is disabled; set DEEPSEEK_API_KEY first"
                )
                return 2
            suite_result = run_harness_suite(
                args.suite,
                planner_client=planner_client,
                dataset_format=args.dataset_format,
                source_repo=args.source_repo,
                checkout_ref=args.checkout_ref,
            )
            _print_harness_suite_report(suite_result, sys.stdout, args.format)
            return 0
        return run_interactive_shell(initial_workdir=workdir)
    _restore_snapshot(WorkspaceSnapshotManager(config.storage_dir), args.snapshot_id, sys.stdout)
    return 0


def main(argv: list[str] | None = None) -> int:  # pylint: disable=too-many-branches
    """Run the CLI command."""
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if not effective_argv:
        return run_interactive_shell(initial_workdir=Path.cwd())

    args = build_parser().parse_args(effective_argv)
    workdir = Path(args.workdir).resolve()
    if args.tui:
        return run_tui_shell(initial_workdir=workdir)
    if args.command is None:
        return run_interactive_shell(initial_workdir=workdir)
    return _run_subcommand(args, workdir)


if __name__ == "__main__":
    raise SystemExit(main())
