"""Task session runner combining planning, local context, GitHub API context, and execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codepilot.core.models import TaskRequest, validate_task_request
from codepilot.executor.shell import PersistentShellSession, ShellCommandResult
from codepilot.integrations.github import (
    GitHubRepoClient,
    GitHubRepoRef,
    GitHubRepoSnapshot,
    infer_github_repo_from_local,
)
from codepilot.planner.workflow import PlanExecutionController, PlanStartResponse
from codepilot.tools.capabilities import default_capability_set
from codepilot.tools.search import glob_search


@dataclass(frozen=True, slots=True)
class TaskSessionResult:
    """Structured result for a single CodePilot runtime session."""

    request: TaskRequest
    plan: PlanStartResponse
    local_files: list[str]
    github_snapshot: GitHubRepoSnapshot | None
    command_results: list[ShellCommandResult]


def run_task_session(
    *,
    description: str,
    workdir: str | Path,
    mode: str,
    github_repo: GitHubRepoRef | None = None,
    github_client: GitHubRepoClient | None = None,
    command_allowlist: tuple[str, ...] | None = None,
) -> TaskSessionResult:
    """Run a planning/execution session enriched with repository context."""
    request = validate_task_request(description, str(workdir), mode)
    controller = PlanExecutionController(default_capability_set())
    plan = controller.start_task(request.description, request.workdir, request.mode)
    local_files = _collect_local_files(Path(request.workdir))
    snapshot = _load_github_snapshot(Path(request.workdir), github_repo, github_client)
    command_results = _execute_allowed_commands(
        Path(request.workdir),
        plan,
        request.mode,
        command_allowlist,
    )
    return TaskSessionResult(
        request=request,
        plan=plan,
        local_files=local_files,
        github_snapshot=snapshot,
        command_results=command_results,
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
) -> list[ShellCommandResult]:
    if mode != "auto":
        return []

    allowed_commands = set(command_allowlist or plan.candidate_commands)
    selected_commands = [
        command for command in plan.candidate_commands if command in allowed_commands
    ]
    session = PersistentShellSession(workdir=workdir)
    return [session.run(command) for command in selected_commands]
