"""Task session runner combining planning, local context, API context, history, and execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from codepilot.core.models import TaskRequest, validate_task_request
from codepilot.executor.shell import PersistentShellSession, ShellCommandResult
from codepilot.integrations.deepseek import (
    DeepSeekPlannerClient,
    FileEditSuggestion,
    PlannerSuggestion,
)
from codepilot.integrations.github import (
    GitHubRepoClient,
    GitHubRepoRef,
    GitHubRepoSnapshot,
    infer_github_repo_from_local,
)
from codepilot.planner.workflow import PlanExecutionController, PlanStartResponse
from codepilot.storage.session_store import SessionRecord, SessionStore, WorkspaceSnapshotManager
from codepilot.tools.capabilities import default_capability_set
from codepilot.tools.filesystem import (
    FileEditResult,
    edit_file_by_replacement,
    write_file_contents,
)
from codepilot.tools.search import glob_search
from codepilot.workspace.inspector import inspect_workspace


@dataclass(frozen=True, slots=True)
class AppliedFileEdit:
    """A file edit attempted during auto execution."""

    path: str
    diff: list[str]
    syntax_check: str
    applied: bool
    reverted: bool


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """Decision describing whether auto execution should attempt another repair round."""

    should_retry: bool
    failure_type: str
    reason: str


@dataclass(frozen=True, slots=True)
class AutoExecutionAttempt:
    """Observed outcome for one auto-execution attempt."""

    attempt_index: int
    failure_type: str
    summary: str
    commands: list[str]
    retried: bool
    reason: str


@dataclass(frozen=True, slots=True)
class PlannerAttempt:
    """Observed planner source used for one planning round."""

    attempt_index: int
    source: str
    summary: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionBudgetSummary:
    """Observed execution budget usage for a session."""

    command_limit: int | None
    command_used: int
    command_exhausted: bool
    edit_limit: int | None
    edit_used: int
    edit_exhausted: bool
    stop_reason: str | None


@dataclass(frozen=True, slots=True)
class TaskSessionResult:  # pylint: disable=too-many-instance-attributes
    """Structured result for a single CodePilot runtime session."""

    session_id: str
    request: TaskRequest
    plan: PlanStartResponse
    local_files: list[str]
    inspected_files: list[str]
    github_snapshot: GitHubRepoSnapshot | None
    edit_results: list[AppliedFileEdit]
    command_results: list[ShellCommandResult]
    planner_trace: list[PlannerAttempt]
    retry_trace: list[AutoExecutionAttempt]
    failure_hints: list[str]
    rollback_snapshot_id: str | None
    execution_budget: ExecutionBudgetSummary | None = None


def run_task_session(  # pylint: disable=too-many-arguments,too-many-locals
    *,
    description: str,
    workdir: str | Path,
    mode: str,
    github_repo: GitHubRepoRef | None = None,
    github_client: GitHubRepoClient | None = None,
    planner_client: DeepSeekPlannerClient | None = None,
    command_allowlist: tuple[str, ...] | None = None,
    strict_command_allowlist: bool = False,
    storage_dir: str | Path | None = None,
    max_auto_retries: int = 1,
    max_command_results: int | None = None,
    max_edit_results: int | None = None,
) -> TaskSessionResult:
    """Run a planning/execution session enriched with repository context."""
    request = validate_task_request(description, str(workdir), mode)
    workdir_path = Path(request.workdir).resolve()
    session_id = uuid4().hex[:12]
    session_store = SessionStore(storage_dir or workdir_path / ".codepilot")
    snapshot_manager = WorkspaceSnapshotManager(storage_dir or workdir_path / ".codepilot")

    workspace_profile = inspect_workspace(workdir_path, request.description)
    controller = PlanExecutionController(default_capability_set())
    plan = controller.start_task(
        request.description,
        request.workdir,
        request.mode,
        workspace_profile=workspace_profile,
    )
    local_files = _collect_local_files(workdir_path, workspace_profile.candidate_files)
    inspected_files = _select_inspected_files(workdir_path, local_files, plan.candidate_files)
    snapshot_id = snapshot_manager.create_snapshot(local_files)
    github_snapshot = _load_github_snapshot(workdir_path, github_repo, github_client)

    edit_results: list[AppliedFileEdit] = []
    command_results: list[ShellCommandResult] = []
    planner_trace: list[PlannerAttempt] = []
    retry_trace: list[AutoExecutionAttempt] = []
    failure_context: list[dict[str, object]] = []
    previous_attempts: list[dict[str, object]] = []
    retry_count = 0
    command_budget_exhausted = False
    edit_budget_exhausted = False
    budget_stop_reason: str | None = None

    while True:
        file_context = _read_file_context(inspected_files)
        planner_candidate_files = tuple(
            dict.fromkeys(
                [
                    *plan.candidate_files,
                    *(_to_relative(workdir_path, path) for path in inspected_files),
                ]
            )
        )
        plan, planner_suggestion, planner_attempt = _apply_planner_suggestion(
            plan,
            request,
            planner_client,
            controller,
            candidate_files=planner_candidate_files,
            file_context=file_context,
            failure_context=failure_context,
            previous_attempts=tuple(previous_attempts),
            workspace_summary=workspace_profile.summary,
        )
        planner_trace.append(
            PlannerAttempt(
                attempt_index=retry_count + 1,
                source=planner_attempt.source,
                summary=plan.summary,
                note=planner_attempt.note,
            )
        )
        inspected_files = _select_inspected_files(
            workdir_path,
            local_files,
            (
                planner_suggestion.file_reads
                if planner_suggestion is not None
                else plan.candidate_files
            ),
        )

        remaining_edit_budget = (
            None if max_edit_results is None else max(0, max_edit_results - len(edit_results))
        )
        attempt_write_results, write_truncated = _apply_file_writes(
            workdir=workdir_path,
            mode=request.mode,
            file_writes=(
                getattr(planner_suggestion, "file_writes", [])
                if planner_suggestion is not None
                else []
            ),
            max_results=remaining_edit_budget,
        )
        remaining_edit_budget_after_writes = (
            None
            if remaining_edit_budget is None
            else max(0, remaining_edit_budget - len(attempt_write_results))
        )
        attempt_edit_results, edit_truncated = _apply_file_edits(
            workdir=workdir_path,
            mode=request.mode,
            file_edits=planner_suggestion.file_edits if planner_suggestion is not None else [],
            max_results=remaining_edit_budget_after_writes,
        )
        edit_results.extend([*attempt_write_results, *attempt_edit_results])
        remaining_command_budget = (
            None
            if max_command_results is None
            else max(0, max_command_results - len(command_results))
        )
        attempt_command_results = _execute_allowed_commands(
            workdir_path,
            plan,
            request.mode,
            command_allowlist,
            strict_command_allowlist,
            max_commands=remaining_command_budget,
        )
        if isinstance(attempt_command_results, tuple) and len(attempt_command_results) == 2:
            attempt_command_results, command_truncated = attempt_command_results
        else:
            command_truncated = False
        command_results.extend(attempt_command_results)

        if write_truncated or edit_truncated or command_truncated:
            edit_budget_exhausted = edit_budget_exhausted or write_truncated or edit_truncated
            command_budget_exhausted = command_budget_exhausted or command_truncated
            budget_stop_reason = _build_budget_stop_reason(
                write_truncated=write_truncated,
                edit_truncated=edit_truncated,
                command_truncated=command_truncated,
            )

        retry_decision = _build_retry_decision(
            mode=request.mode,
            planner_client=planner_client,
            command_results=attempt_command_results,
            edit_results=attempt_edit_results,
            retry_count=retry_count,
            max_auto_retries=max_auto_retries,
        )
        if budget_stop_reason is not None:
            retry_decision = RetryDecision(False, retry_decision.failure_type, budget_stop_reason)
        retry_trace.append(
            AutoExecutionAttempt(
                attempt_index=retry_count + 1,
                failure_type=retry_decision.failure_type,
                summary=plan.summary,
                commands=[result.command for result in attempt_command_results],
                retried=retry_decision.should_retry,
                reason=retry_decision.reason,
            )
        )

        if not retry_decision.should_retry:
            break

        failure_target_files = _extract_failure_target_files(
            attempt_command_results,
            attempt_edit_results,
            workdir_path,
        )
        failure_context = _build_failure_context(
            attempt_command_results,
            attempt_edit_results,
            retry_decision.failure_type,
            failure_target_files=failure_target_files,
        )
        previous_attempts.append(
            _summarize_attempt(
                plan,
                attempt_edit_results,
                attempt_command_results,
                retry_decision.failure_type,
            )
        )
        local_files = _collect_local_files(workdir_path, plan.candidate_files)
        inspected_files = _select_inspected_files(
            workdir_path,
            local_files,
            [*failure_target_files, *plan.candidate_files],
        )
        retry_count += 1

    local_files = _collect_local_files(workdir_path, plan.candidate_files)
    inspected_files = _select_inspected_files(workdir_path, local_files, plan.candidate_files)

    _persist_session(
        session_store=session_store,
        session_id=session_id,
        request=request,
        plan=plan,
        command_results=command_results,
    )
    execution_budget = ExecutionBudgetSummary(
        command_limit=max_command_results,
        command_used=len(command_results),
        command_exhausted=command_budget_exhausted,
        edit_limit=max_edit_results,
        edit_used=len(edit_results),
        edit_exhausted=edit_budget_exhausted,
        stop_reason=budget_stop_reason,
    )
    failure_hints = _build_failure_hints(edit_results, command_results, planner_trace)
    if budget_stop_reason is not None:
        failure_hints = [f"执行预算已耗尽：{budget_stop_reason}", *failure_hints]
    result = TaskSessionResult(
        session_id=session_id,
        request=request,
        plan=plan,
        local_files=local_files,
        inspected_files=inspected_files,
        github_snapshot=github_snapshot,
        edit_results=edit_results,
        command_results=command_results,
        planner_trace=planner_trace,
        retry_trace=retry_trace,
        failure_hints=failure_hints,
        rollback_snapshot_id=snapshot_id,
        execution_budget=execution_budget,
    )
    _persist_logs(session_store, result)
    return result


def _apply_planner_suggestion(  # pylint: disable=too-many-arguments
    plan: PlanStartResponse,
    request: TaskRequest,
    planner_client: DeepSeekPlannerClient | None,
    controller: PlanExecutionController,
    *,
    candidate_files: tuple[str, ...],
    file_context: dict[str, str],
    failure_context: list[dict[str, object]] | None = None,
    previous_attempts: tuple[dict[str, object], ...] = (),
    workspace_summary: str = "",
) -> tuple[PlanStartResponse, PlannerSuggestion | None, PlannerAttempt]:
    if planner_client is None:
        return plan, None, PlannerAttempt(0, "workspace", plan.summary, "DeepSeek planner disabled")
    try:
        suggestion = planner_client.generate_plan(
            task_description=request.description,
            workdir=request.workdir,
            capabilities=tuple(capability.name for capability in controller.capabilities),
            candidate_files=candidate_files,
            file_context=file_context,
            failure_context=failure_context,
            previous_attempts=previous_attempts,
            workspace_summary=workspace_summary,
        )
    except TypeError:
        try:
            suggestion = planner_client.generate_plan(
                task_description=request.description,
                workdir=request.workdir,
                capabilities=tuple(capability.name for capability in controller.capabilities),
            )
        except (OSError, TimeoutError, ValueError) as exc:
            note = _format_planner_error(exc)
            fallback_plan = replace(
                plan,
                summary=f"{plan.summary} Planner fallback activated: {note}.",
            )
            return fallback_plan, None, PlannerAttempt(0, "fallback", fallback_plan.summary, note)
        suggestion = PlannerSuggestion(
            summary=str(getattr(suggestion, "summary", plan.summary)),
            steps=tuple(getattr(suggestion, "steps", plan.steps)),
            candidate_commands=list(
                getattr(suggestion, "candidate_commands", plan.candidate_commands)
            ),
            file_reads=list(getattr(suggestion, "file_reads", [])),
            file_edits=list(getattr(suggestion, "file_edits", [])),
            file_writes=list(getattr(suggestion, "file_writes", [])),
        )
    except (OSError, TimeoutError, ValueError) as exc:
        note = _format_planner_error(exc)
        fallback_plan = replace(
            plan,
            summary=f"{plan.summary} Planner fallback activated: {note}.",
        )
        return fallback_plan, None, PlannerAttempt(0, "fallback", fallback_plan.summary, note)
    candidate_commands = _select_safe_candidate_commands(
        suggestion.candidate_commands,
        plan.candidate_commands,
    )
    merged_candidate_files = _merge_candidate_files(plan.candidate_files, suggestion.file_reads)
    enriched_plan = replace(
        plan,
        summary=suggestion.summary,
        steps=suggestion.steps or plan.steps,
        candidate_files=merged_candidate_files,
        candidate_commands=candidate_commands,
    )
    return enriched_plan, suggestion, PlannerAttempt(0, "deepseek", enriched_plan.summary)


def _format_planner_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    compact = " ".join(message.split())
    if len(compact) > 120:
        compact = f"{compact[:117]}..."
    return compact


def _merge_candidate_files(
    baseline_files: list[str],
    suggested_files: list[str],
    *,
    limit: int = 8,
) -> list[str]:
    merged: list[str] = []
    for path in [*suggested_files, *baseline_files]:
        if path and path not in merged:
            merged.append(path)
        if len(merged) >= limit:
            break
    return merged or baseline_files


def _select_safe_candidate_commands(
    suggested_commands: list[str],
    baseline_commands: list[str],
) -> list[str]:
    if not suggested_commands:
        return baseline_commands
    allowed = [command for command in suggested_commands if command in baseline_commands]
    return allowed or baseline_commands


def _collect_local_files(workdir: Path, preferred_files: list[str]) -> list[str]:
    patterns = ("README*", "pyproject.toml", "docs/**/*.md", "src/**/*.py", "tests/**/*.py")
    results: list[str] = list(preferred_files)
    for pattern in patterns:
        results.extend(glob_search(workdir, pattern, limit=20))
    unique_files = [path for path in sorted(set(results)) if Path(path).is_file()]
    return unique_files[:40]


def _select_inspected_files(
    workdir: Path,
    local_files: list[str],
    suggested_files: list[str],
    *,
    limit: int = 6,
) -> list[str]:
    resolved: list[str] = []
    for raw_path in [*suggested_files, *local_files]:
        candidate = _resolve_workspace_file(workdir, raw_path)
        if candidate is None or candidate in resolved:
            continue
        resolved.append(candidate)
        if len(resolved) >= limit:
            break
    return resolved


def _read_file_context(paths: list[str], *, max_chars: int = 1200) -> dict[str, str]:
    context: dict[str, str] = {}
    for raw_path in paths:
        path = Path(raw_path)
        content = path.read_text(encoding="utf-8")
        context[path.name if path.name not in context else str(path)] = content[:max_chars]
    return context


def _load_github_snapshot(
    workdir: Path,
    github_repo: GitHubRepoRef | None,
    github_client: GitHubRepoClient | None,
) -> GitHubRepoSnapshot | None:
    repo_ref = github_repo or infer_github_repo_from_local(workdir)
    if repo_ref is None:
        return None
    client = github_client or GitHubRepoClient()
    return client.fetch_snapshot(repo_ref)


def _apply_file_writes(
    *,
    workdir: Path,
    mode: str,
    file_writes: list[object],
    max_results: int | None = None,
) -> tuple[list[AppliedFileEdit], bool]:
    if mode != "auto":
        return [], False
    results: list[AppliedFileEdit] = []
    truncated = False
    for suggestion in file_writes:
        if max_results is not None and len(results) >= max_results:
            truncated = True
            break
        target = _resolve_workspace_path(
            workdir, str(getattr(suggestion, "path", "")), require_exists=False
        )
        if target is None:
            continue
        try:
            edit_result = write_file_contents(
                target,
                str(getattr(suggestion, "content", "")),
                restore_on_syntax_error=True,
            )
        except ValueError as exc:
            results.append(
                AppliedFileEdit(
                    path=str(Path(target).resolve()),
                    diff=[],
                    syntax_check=f"error: {exc}",
                    applied=False,
                    reverted=False,
                )
            )
            continue
        results.append(_to_applied_file_edit(target, edit_result))
    return results, truncated


def _apply_file_edits(
    *,
    workdir: Path,
    mode: str,
    file_edits: list[FileEditSuggestion],
    max_results: int | None = None,
) -> tuple[list[AppliedFileEdit], bool]:
    if mode != "auto":
        return [], False
    results: list[AppliedFileEdit] = []
    truncated = False
    for suggestion in file_edits:
        if max_results is not None and len(results) >= max_results:
            truncated = True
            break
        target = _resolve_workspace_file(workdir, suggestion.path)
        if target is None or not Path(target).is_file() or not suggestion.old_string:
            continue
        try:
            edit_result = edit_file_by_replacement(
                target,
                suggestion.old_string,
                suggestion.new_string,
                replace_all=suggestion.replace_all,
                restore_on_syntax_error=True,
            )
        except ValueError as exc:
            results.append(
                AppliedFileEdit(
                    path=str(Path(target).resolve()),
                    diff=[],
                    syntax_check=f"error: {exc}",
                    applied=False,
                    reverted=False,
                )
            )
            continue
        results.append(_to_applied_file_edit(target, edit_result))
    return results, truncated


def _to_applied_file_edit(path: str | Path, edit_result: FileEditResult) -> AppliedFileEdit:
    return AppliedFileEdit(
        path=str(Path(path).resolve()),
        diff=edit_result.diff,
        syntax_check=edit_result.syntax_check,
        applied=edit_result.applied,
        reverted=edit_result.reverted,
    )


def _resolve_workspace_path(
    workdir: Path,
    raw_path: str,
    *,
    require_exists: bool,
) -> str | None:
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (workdir / candidate).resolve()
    try:
        resolved.relative_to(workdir)
    except ValueError:
        return None
    if require_exists and not resolved.exists():
        return None
    return str(resolved)


def _resolve_workspace_file(workdir: Path, raw_path: str) -> str | None:
    return _resolve_workspace_path(workdir, raw_path, require_exists=True)


def _to_relative(workdir: Path, raw_path: str) -> str:
    path = Path(raw_path).resolve()
    try:
        return path.relative_to(workdir).as_posix()
    except ValueError:
        return path.as_posix()


def _execute_allowed_commands(
    workdir: Path,
    plan: PlanStartResponse,
    mode: str,
    command_allowlist: tuple[str, ...] | None,
    strict_command_allowlist: bool,
    max_commands: int | None = None,
) -> tuple[list[ShellCommandResult], bool]:
    if mode != "auto":
        return [], False

    if command_allowlist is None:
        allowed_commands = set(plan.candidate_commands)
    else:
        allowed_commands = set(command_allowlist)
        disallowed = [
            command for command in plan.candidate_commands if command not in allowed_commands
        ]
        if strict_command_allowlist and disallowed:
            raise PermissionError("candidate commands contain items outside the allowlist")

    selected_commands = [
        command for command in plan.candidate_commands if command in allowed_commands
    ]
    if max_commands is not None:
        selected_commands = selected_commands[:max_commands]
        truncated = len(plan.candidate_commands) > len(selected_commands)
    else:
        truncated = False
    session = PersistentShellSession(workdir=workdir)
    return [session.run(command) for command in selected_commands], truncated


def _build_retry_decision(
    *,
    mode: str,
    planner_client: DeepSeekPlannerClient | None,
    command_results: list[ShellCommandResult],
    edit_results: list[AppliedFileEdit],
    retry_count: int,
    max_auto_retries: int,
) -> RetryDecision:
    failure_type = _classify_failure(command_results, edit_results)
    if mode != "auto":
        return RetryDecision(False, failure_type, "plan mode does not auto-retry")
    if planner_client is None:
        return RetryDecision(False, failure_type, "planner client unavailable")
    if retry_count >= max_auto_retries:
        return RetryDecision(False, failure_type, "retry budget exhausted")
    if failure_type == "success":
        return RetryDecision(False, failure_type, "verification passed")

    retryable_types = {
        "assertion_failure": "pytest assertion mismatch is repairable by replanning once",
        "import_error": "missing import/module errors are repairable by focused replanning",
        "lint_failure": "lint-only failures can be repaired without changing overall strategy",
        "syntax_error": "syntax-breaking edits should trigger a focused repair attempt",
        "edit_application_failure": (
            "deterministic edit mismatches can be repaired by replanning with failure context"
        ),
    }
    reason = retryable_types.get(failure_type)
    if reason is None:
        return RetryDecision(False, failure_type, "failure type not eligible for auto-retry")
    return RetryDecision(True, failure_type, reason)


def _build_budget_stop_reason(
    *,
    write_truncated: bool,
    edit_truncated: bool,
    command_truncated: bool,
) -> str:
    reasons: list[str] = []
    if write_truncated or edit_truncated:
        reasons.append("edit budget exhausted")
    if command_truncated:
        reasons.append("command budget exhausted")
    if len(reasons) == 1:
        return reasons[0]
    return " and ".join(reasons)


def _classify_failure(  # pylint: disable=too-many-return-statements
    command_results: list[ShellCommandResult],
    edit_results: list[AppliedFileEdit],
) -> str:
    for edit_result in edit_results:
        if edit_result.reverted and edit_result.syntax_check.startswith("error:"):
            return "syntax_error"
        if not edit_result.applied:
            return "edit_application_failure"
    failed_commands = [result for result in command_results if result.exit_code != 0]
    if not failed_commands:
        return "success"
    combined_output = "\n".join(
        f"{result.command}\n{result.stdout}\n{result.stderr}" for result in failed_commands
    ).lower()
    if "modulenotfounderror" in combined_output or "importerror" in combined_output:
        return "import_error"
    if (
        "syntaxerror" in combined_output
        or "indentationerror" in combined_output
        or "unexpected indent" in combined_output
        or "eol while scanning string literal" in combined_output
    ):
        return "syntax_error"
    if "ruff" in combined_output or any("ruff" in result.command for result in failed_commands):
        return "lint_failure"
    if "assert" in combined_output or "failed" in combined_output:
        return "assertion_failure"
    if "command not found" in combined_output or "no such file or directory" in combined_output:
        return "environment_error"
    return "unknown_failure"


def _build_failure_context(
    command_results: list[ShellCommandResult],
    edit_results: list[AppliedFileEdit],
    failure_type: str,
    *,
    failure_target_files: list[str] | None = None,
) -> list[dict[str, object]]:
    context: list[dict[str, object]] = []
    for result in command_results:
        if result.exit_code == 0:
            continue
        context.append(
            {
                "command": result.command,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "failure_type": failure_type,
                "target_files": failure_target_files or [],
            }
        )
    for edit_result in edit_results:
        if edit_result.applied and not edit_result.reverted:
            continue
        context.append(
            {
                "path": edit_result.path,
                "syntax_check": edit_result.syntax_check,
                "applied": edit_result.applied,
                "reverted": edit_result.reverted,
                "failure_type": failure_type,
                "target_files": failure_target_files or [],
            }
        )
    return context


def _extract_failure_target_files(
    command_results: list[ShellCommandResult],
    edit_results: list[AppliedFileEdit],
    workdir: Path,
) -> list[str]:
    targets: list[str] = []
    for result in command_results:
        if result.exit_code == 0:
            continue
        text = "\n".join((result.command, result.stdout, result.stderr))
        targets.extend(_extract_paths_from_text(text, workdir))
    for edit_result in edit_results:
        if not edit_result.applied or edit_result.reverted:
            targets.append(_to_relative(workdir, edit_result.path))
    return list(dict.fromkeys(targets))


def _extract_paths_from_text(text: str, workdir: Path) -> list[str]:
    path_pattern = re.compile(r"(?:[A-Za-z]:)?(?:/[^\s:'\"]+)+\.[A-Za-z0-9_]+")
    discovered: list[str] = []
    for match in path_pattern.findall(text):
        candidate = match.strip("'\"()[],:;")
        candidate_path = Path(candidate)
        resolved = candidate_path if candidate_path.is_absolute() else (workdir / candidate_path)
        try:
            resolved = resolved.resolve()
            resolved.relative_to(workdir)
        except Exception:  # pragma: no cover - defensive path filtering
            continue
        if resolved.exists():
            discovered.append(str(resolved))
    return discovered


def _summarize_attempt(
    plan: PlanStartResponse,
    edit_results: list[AppliedFileEdit],
    command_results: list[ShellCommandResult],
    failure_type: str,
) -> dict[str, object]:
    return {
        "summary": plan.summary,
        "failure_type": failure_type,
        "commands": [result.command for result in command_results],
        "failed_commands": [result.command for result in command_results if result.exit_code != 0],
        "edited_files": [edit_result.path for edit_result in edit_results],
    }


def _persist_session(
    *,
    session_store: SessionStore,
    session_id: str,
    request: TaskRequest,
    plan: PlanStartResponse,
    command_results: list[ShellCommandResult],
) -> None:
    created_at = datetime.now(tz=UTC).isoformat()
    all_succeeded = all(item.exit_code == 0 for item in command_results)
    status = "completed" if all_succeeded else "pending_review"
    if not command_results:
        status = plan.status
    record = SessionRecord(
        session_id=session_id,
        description=request.description,
        mode=request.mode,
        status=status,
        workdir=request.workdir,
        created_at=created_at,
        risk_level=plan.risk.level,
        commands=[item.command for item in command_results],
    )
    session_store.save_session(record)


def _build_failure_hints(
    edit_results: list[AppliedFileEdit],
    command_results: list[ShellCommandResult],
    planner_trace: list[PlannerAttempt],
) -> list[str]:
    hints: list[str] = []
    for planner_attempt in planner_trace:
        if planner_attempt.source == "fallback" and planner_attempt.note:
            hints.append(f"DeepSeek planner 不可用，已回退到本地工作区规划：{planner_attempt.note}")
    for edit_result in edit_results:
        if edit_result.reverted and edit_result.syntax_check.startswith("error:"):
            hints.append(
                "检测到语法错误，已回退 "
                f"{Path(edit_result.path).name} 的自动修改："
                f"{edit_result.syntax_check}"
            )
        elif not edit_result.applied:
            hints.append(
                f"自动修改未能应用到 {Path(edit_result.path).name}：{edit_result.syntax_check}"
            )
    for result in command_results:
        if result.exit_code == 0:
            continue
        failure_type = _classify_failure([result], [])
        if "pytest" in result.command:
            hints.append("pytest 未通过：先查看失败用例、断言差异和测试夹具是否与当前实现一致。")
        if failure_type == "assertion_failure":
            hints.append("检测到断言失败：优先核对预期输出、边界值和测试数据，而不是直接绕过测试。")
        elif failure_type == "import_error":
            hints.append("检测到依赖或导入缺失：检查虚拟环境、安装状态与 Python 模块路径。")
        elif failure_type == "syntax_error":
            hints.append("检测到语法错误：优先检查缩进、括号、引号和新增文件内容是否完整。")
        elif failure_type == "lint_failure":
            hints.append("Ruff 检查未通过：先修复格式或静态规则，再重新执行质量门禁。")
        elif failure_type == "environment_error":
            hints.append(
                "检测到环境级失败：先确认命令、依赖和工作目录有效，再决定是否继续自动修复。"
            )
        else:
            hints.append(
                f"命令 {result.command} 执行失败：请先阅读 stderr 与退出码，再决定重试或回退。"
            )
    return list(dict.fromkeys(hints))


def _persist_logs(session_store: SessionStore, result: TaskSessionResult) -> None:
    session_store.append_log(result.session_id, f"plan_status={result.plan.status}")
    session_store.append_log(
        result.session_id,
        f"risk={result.plan.risk.level}:{result.plan.risk.reason}",
    )
    if result.inspected_files:
        inspected_preview = ",".join(
            _to_relative(Path(result.request.workdir).resolve(), path)
            for path in result.inspected_files[:5]
        )
        session_store.append_log(
            result.session_id,
            f"inspected_files={inspected_preview}",
        )
    if result.plan.candidate_files:
        session_store.append_log(
            result.session_id,
            f"candidate_files={','.join(result.plan.candidate_files[:5])}",
        )
    if result.plan.candidate_commands:
        session_store.append_log(
            result.session_id,
            f"candidate_commands={','.join(result.plan.candidate_commands)}",
        )
    if result.rollback_snapshot_id:
        session_store.append_log(result.session_id, f"snapshot={result.rollback_snapshot_id}")
    for planner_attempt in result.planner_trace:
        note = f" note={planner_attempt.note}" if planner_attempt.note else ""
        session_store.append_log(
            result.session_id,
            "planner_attempt="
            f"{planner_attempt.attempt_index}"
            f" source={planner_attempt.source}"
            f" summary={planner_attempt.summary}{note}",
        )
    for attempt in result.retry_trace:
        session_store.append_log(
            result.session_id,
            "retry_attempt="
            f"{attempt.attempt_index}"
            f" failure={attempt.failure_type}"
            f" retried={attempt.retried}"
            f" reason={attempt.reason}",
        )
    for edit_result in result.edit_results:
        session_store.append_log(
            result.session_id,
            "edit="
            f"{_to_relative(Path(result.request.workdir).resolve(), edit_result.path)}"
            f" applied={edit_result.applied}"
            f" reverted={edit_result.reverted}"
            f" syntax={edit_result.syntax_check}",
        )
    for command_result in result.command_results:
        session_store.append_log(
            result.session_id,
            f"command={command_result.command} exit={command_result.exit_code}",
        )
    for hint in result.failure_hints:
        session_store.append_log(result.session_id, f"hint={hint}")
