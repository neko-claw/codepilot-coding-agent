"""Harness execution helpers for developer-day workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codepilot.eval import (
    BenchmarkSuiteResult,
    SWEBenchSuiteRunResult,
    load_benchmark_cases,
    run_benchmark_suite,
    run_swebench_suite,
)
from codepilot.runtime.session import TaskSessionResult, _extract_failure_target_files, run_task_session
from codepilot.storage.session_store import SessionStore


@dataclass(frozen=True, slots=True)
class HarnessLoopRound:
    """One codex-like harness loop iteration."""

    round_index: int
    session_result: TaskSessionResult
    success: bool
    reason: str


@dataclass(frozen=True, slots=True)
class HarnessLoopResult:
    """Aggregate result for a closed-loop harness run."""

    description: str
    workdir: str
    rounds: list[HarnessLoopRound]
    completed: bool
    stop_reason: str


def run_harness_session(
    *,
    description: str,
    workdir: str | Path,
    mode: str = "auto",
    planner_client: Any | None = None,
    command_allowlist: tuple[str, ...] | None = None,
    strict_command_allowlist: bool = False,
    storage_dir: str | Path | None = None,
    max_auto_retries: int = 1,
    max_command_results: int | None = None,
    max_edit_results: int | None = None,
) -> TaskSessionResult:
    """Run one developer harness session and return the underlying runtime result."""
    return run_task_session(
        description=description,
        workdir=workdir,
        mode=mode,
        planner_client=planner_client,
        command_allowlist=command_allowlist,
        strict_command_allowlist=strict_command_allowlist,
        storage_dir=storage_dir,
        max_auto_retries=max_auto_retries,
        max_command_results=max_command_results,
        max_edit_results=max_edit_results,
    )


def run_harness_suite(
    suite_path: str | Path,
    *,
    planner_client: Any,
    dataset_format: str = "auto",
    source_repo: str | Path | None = None,
    checkout_ref: str | None = None,
) -> BenchmarkSuiteResult | SWEBenchSuiteRunResult:
    """Run a benchmark suite through the harness pipeline."""
    cases = load_benchmark_cases(suite_path, dataset_format=dataset_format)
    if dataset_format == "swebench":
        return run_swebench_suite(
            cases,
            planner_client,
            source_repo=source_repo,
            checkout_ref=checkout_ref,
        )
    return run_benchmark_suite(cases, planner_client)


def resume_harness_session(
    session_id: str,
    *,
    storage_dir: str | Path,
    planner_client: Any | None,
    mode: str | None = None,
    max_auto_retries: int = 1,
    strict_command_allowlist: bool = False,
    max_command_results: int | None = None,
    max_edit_results: int | None = None,
) -> TaskSessionResult:
    """Resume a previously recorded harness session using saved history metadata."""
    store = SessionStore(storage_dir)
    record = store.get_session(session_id)
    if record is None:
        raise FileNotFoundError(f"session not found: {session_id}")
    return run_harness_session(
        description=record.description,
        workdir=record.workdir,
        mode=mode or record.mode,
        planner_client=planner_client,
        command_allowlist=tuple(record.commands) or None,
        strict_command_allowlist=strict_command_allowlist,
        storage_dir=storage_dir,
        max_auto_retries=max_auto_retries,
        max_command_results=max_command_results,
        max_edit_results=max_edit_results,
    )


def run_harness_loop(
    *,
    description: str,
    workdir: str | Path,
    planner_client: Any | None,
    mode: str = "auto",
    max_rounds: int = 3,
    command_allowlist: tuple[str, ...] | None = None,
    strict_command_allowlist: bool = False,
    storage_dir: str | Path | None = None,
    max_auto_retries: int = 1,
    max_command_results: int | None = None,
    max_edit_results: int | None = None,
) -> HarnessLoopResult:
    """Run repeated harness sessions until one succeeds or the loop budget is exhausted."""
    workdir_path = Path(workdir).resolve()
    rounds: list[HarnessLoopRound] = []
    attempt_description = description
    for round_index in range(1, max_rounds + 1):
        result = run_harness_session(
            description=attempt_description,
            workdir=workdir_path,
            mode=mode,
            planner_client=planner_client,
            command_allowlist=command_allowlist,
            strict_command_allowlist=strict_command_allowlist,
            storage_dir=storage_dir,
            max_auto_retries=max_auto_retries,
            max_command_results=max_command_results,
            max_edit_results=max_edit_results,
        )
        success, reason = _classify_loop_round(result)
        rounds.append(
            HarnessLoopRound(
                round_index=round_index,
                session_result=result,
                success=success,
                reason=reason,
            )
        )
        if success:
            return HarnessLoopResult(
                description=description,
                workdir=str(workdir_path),
                rounds=rounds,
                completed=True,
                stop_reason="success",
            )
        attempt_description = _build_loop_retry_description(description, result, round_index)
    return HarnessLoopResult(
        description=description,
        workdir=str(workdir_path),
        rounds=rounds,
        completed=False,
        stop_reason="max_rounds_exhausted",
    )


def _classify_loop_round(result: TaskSessionResult) -> tuple[bool, str]:
    execution_budget = getattr(result, "execution_budget", None)
    if execution_budget is not None and execution_budget.stop_reason:
        return False, execution_budget.stop_reason
    failed_commands = [item for item in result.command_results if item.exit_code != 0]
    if failed_commands:
        return False, _format_failure_reason(result)
    failed_edits = [item for item in result.edit_results if not item.applied or item.reverted]
    if failed_edits:
        return False, _format_failure_reason(result)
    return True, "verification passed"


def _build_loop_retry_description(
    base_description: str,
    result: TaskSessionResult,
    round_index: int,
) -> str:
    failure_lines: list[str] = []
    if result.failure_hints:
        failure_lines.extend(f"- {hint}" for hint in result.failure_hints)
    execution_budget = getattr(result, "execution_budget", None)
    if execution_budget is not None and execution_budget.stop_reason:
        failure_lines.append(f"- execution budget exhausted: {execution_budget.stop_reason}")
    for command_result in result.command_results:
        if command_result.exit_code == 0:
            continue
        failure_lines.append(
            f"- command failed: {command_result.command} => {command_result.exit_code}"
        )
        if command_result.stderr:
            failure_lines.append(f"  stderr: {command_result.stderr.strip()}")
        if command_result.stdout:
            failure_lines.append(f"  stdout: {command_result.stdout.strip()}")
    for edit_result in result.edit_results:
        if edit_result.applied and not edit_result.reverted:
            continue
        failure_lines.append(f"- edit failed: {edit_result.path}")
        if edit_result.syntax_check:
            failure_lines.append(f"  syntax: {edit_result.syntax_check}")
    target_files = _extract_loop_target_files(result)
    if target_files:
        failure_lines.append("- target files:")
        failure_lines.extend(f"  - {target_file}" for target_file in target_files)
    failure_summary = (
        "\n".join(failure_lines) if failure_lines else "- no explicit failure hints were recorded"
    )
    return (
        f"{base_description}\n\n"
        f"Previous harness round #{round_index} did not converge.\n"
        f"Use the failure context below to re-plan and re-verify.\n"
        f"{failure_summary}"
    )


def _extract_loop_target_files(result: TaskSessionResult) -> list[str]:
    workdir = Path(result.request.workdir)
    command_results = list(getattr(result, "command_results", []))
    edit_results = list(getattr(result, "edit_results", []))
    return _extract_failure_target_files(command_results, edit_results, workdir)


def _format_failure_reason(result: TaskSessionResult) -> str:
    if result.failure_hints:
        return result.failure_hints[0]
    execution_budget = getattr(result, "execution_budget", None)
    if execution_budget is not None and execution_budget.stop_reason:
        return execution_budget.stop_reason
    failed_commands = [item for item in result.command_results if item.exit_code != 0]
    if failed_commands:
        command = failed_commands[0]
        return f"command failed: {command.command} => {command.exit_code}"
    failed_edits = [item for item in result.edit_results if not item.applied or item.reverted]
    if failed_edits:
        edit = failed_edits[0]
        return f"edit failed: {edit.path}"
    return "verification passed"
