"""Task session runner combining planning, local context, API context, history, and execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from codepilot.core.models import TaskRequest, validate_task_request
from codepilot.executor.shell import PersistentShellSession, ShellCommandResult
from codepilot.integrations.deepseek import DeepSeekPlannerClient
from codepilot.integrations.github import (
    GitHubRepoClient,
    GitHubRepoRef,
    GitHubRepoSnapshot,
    infer_github_repo_from_local,
)
from codepilot.planner.workflow import PlanExecutionController, PlanStartResponse
from codepilot.storage.session_store import SessionRecord, SessionStore, WorkspaceSnapshotManager
from codepilot.tools.capabilities import default_capability_set
from codepilot.tools.search import glob_search


@dataclass(frozen=True, slots=True)
class TaskSessionResult:  # pylint: disable=too-many-instance-attributes
    """Structured result for a single CodePilot runtime session."""

    session_id: str
    request: TaskRequest
    plan: PlanStartResponse
    local_files: list[str]
    github_snapshot: GitHubRepoSnapshot | None
    command_results: list[ShellCommandResult]
    failure_hints: list[str]
    rollback_snapshot_id: str | None


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
) -> TaskSessionResult:
    """Run a planning/execution session enriched with repository context."""
    request = validate_task_request(description, str(workdir), mode)
    workdir_path = Path(request.workdir).resolve()
    session_id = uuid4().hex[:12]
    session_store = SessionStore(storage_dir or workdir_path / ".codepilot")
    snapshot_manager = WorkspaceSnapshotManager(storage_dir or workdir_path / ".codepilot")

    controller = PlanExecutionController(default_capability_set())
    plan = controller.start_task(request.description, request.workdir, request.mode)
    plan = _apply_planner_suggestion(plan, request, planner_client, controller)
    local_files = _collect_local_files(workdir_path)
    snapshot_id = snapshot_manager.create_snapshot(local_files)
    github_snapshot = _load_github_snapshot(workdir_path, github_repo, github_client)
    command_results = _execute_allowed_commands(
        workdir_path,
        plan,
        request.mode,
        command_allowlist,
        strict_command_allowlist,
    )

    _persist_session(
        session_store=session_store,
        session_id=session_id,
        request=request,
        plan=plan,
        command_results=command_results,
    )
    failure_hints = _build_failure_hints(command_results)
    result = TaskSessionResult(
        session_id=session_id,
        request=request,
        plan=plan,
        local_files=local_files,
        github_snapshot=github_snapshot,
        command_results=command_results,
        failure_hints=failure_hints,
        rollback_snapshot_id=snapshot_id,
    )
    _persist_logs(session_store, result)
    return result


def _apply_planner_suggestion(
    plan: PlanStartResponse,
    request: TaskRequest,
    planner_client: DeepSeekPlannerClient | None,
    controller: PlanExecutionController,
) -> PlanStartResponse:
    if planner_client is None:
        return plan
    suggestion = planner_client.generate_plan(
        task_description=request.description,
        workdir=request.workdir,
        capabilities=tuple(capability.name for capability in controller.capabilities),
    )
    candidate_commands = suggestion.candidate_commands or plan.candidate_commands
    return replace(
        plan,
        summary=suggestion.summary,
        steps=suggestion.steps or plan.steps,
        candidate_commands=candidate_commands,
    )


def _collect_local_files(workdir: Path) -> list[str]:
    patterns = ("README*", "pyproject.toml", "src/**/*.py", "tests/**/*.py")
    results: list[str] = []
    for pattern in patterns:
        results.extend(glob_search(workdir, pattern, limit=20))
    return sorted(set(results))[:40]


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


def _execute_allowed_commands(
    workdir: Path,
    plan: PlanStartResponse,
    mode: str,
    command_allowlist: tuple[str, ...] | None,
    strict_command_allowlist: bool,
) -> list[ShellCommandResult]:
    if mode != "auto":
        return []

    if command_allowlist is None:
        allowed_commands = set(plan.candidate_commands)
    else:
        allowed_commands = set(command_allowlist)
        disallowed = [
            command
            for command in plan.candidate_commands
            if command not in allowed_commands
        ]
        if strict_command_allowlist and disallowed:
            raise PermissionError("candidate commands contain items outside the allowlist")

    selected_commands = [
        command for command in plan.candidate_commands if command in allowed_commands
    ]
    session = PersistentShellSession(workdir=workdir)
    return [session.run(command) for command in selected_commands]


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


def _build_failure_hints(command_results: list[ShellCommandResult]) -> list[str]:
    hints: list[str] = []
    for result in command_results:
        if result.exit_code == 0:
            continue
        combined_output = f"{result.stdout}\n{result.stderr}".lower()
        if "pytest" in result.command:
            hints.append("pytest 未通过：先查看失败用例、断言差异和测试夹具是否与当前实现一致。")
        if "assert" in combined_output:
            hints.append("检测到断言失败：优先核对预期输出、边界值和测试数据，而不是直接绕过测试。")
        if "modulenotfounderror" in combined_output:
            hints.append("检测到依赖或导入缺失：检查虚拟环境、安装状态与 Python 模块路径。")
        if "ruff" in result.command:
            hints.append("Ruff 检查未通过：先修复格式或静态规则，再重新执行质量门禁。")
        if not hints:
            hints.append(
                f"命令 {result.command} 执行失败：请先阅读 stderr 与退出码，再决定重试或回退。"
            )
    return hints


def _persist_logs(session_store: SessionStore, result: TaskSessionResult) -> None:
    session_store.append_log(result.session_id, f"plan_status={result.plan.status}")
    session_store.append_log(
        result.session_id,
        f"risk={result.plan.risk.level}:{result.plan.risk.reason}",
    )
    if result.rollback_snapshot_id:
        session_store.append_log(result.session_id, f"snapshot={result.rollback_snapshot_id}")
    for command_result in result.command_results:
        session_store.append_log(
            result.session_id,
            f"command={command_result.command} exit={command_result.exit_code}",
        )
    for hint in result.failure_hints:
        session_store.append_log(result.session_id, f"hint={hint}")
