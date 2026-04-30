"""CodePilot package."""

from .core.config import CodePilotConfig, load_config
from .core.models import TaskRequest, validate_task_request
from .executor.interpreter import PythonExecutionResult, execute_python
from .executor.shell import PersistentShellSession, ShellCommandResult
from .harness import (
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
    run_harness_session,
    run_harness_suite,
    serialize_session_result,
    serialize_suite_result,
)
from .integrations.deepseek import DeepSeekPlannerClient, PlannerSuggestion
from .integrations.github import (
    GitHubRepoClient,
    GitHubRepoRef,
    GitHubRepoSnapshot,
    infer_github_repo_from_local,
)
from .planner.workflow import PlanExecutionController, PlanStartResponse
from .runtime.session import ExecutionBudgetSummary, TaskSessionResult, run_task_session
from .safety.guard import evaluate_operation_risk
from .storage.session_store import SessionRecord, SessionStore, WorkspaceSnapshotManager
from .tools.capabilities import ToolCapability, default_capability_set
from .tools.filesystem import (
    FileEditResult,
    FileReadResult,
    edit_file_by_replacement,
    read_file_with_line_numbers,
)
from .tools.search import glob_search, grep_search

__all__ = [
    "CodePilotConfig",
    "ExecutionBudgetSummary",
    "DeepSeekPlannerClient",
    "FileEditResult",
    "FileReadResult",
    "GitHubRepoClient",
    "GitHubRepoRef",
    "GitHubRepoSnapshot",
    "PersistentShellSession",
    "PlanExecutionController",
    "PlanStartResponse",
    "PlannerSuggestion",
    "PythonExecutionResult",
    "SessionRecord",
    "SessionStore",
    "ShellCommandResult",
    "TaskRequest",
    "TaskSessionResult",
    "ToolCapability",
    "WorkspaceSnapshotManager",
    "default_capability_set",
    "edit_file_by_replacement",
    "evaluate_operation_risk",
    "execute_python",
    "format_loop_json",
    "format_loop_markdown",
    "format_loop_text",
    "format_harness_json",
    "format_harness_markdown",
    "format_harness_text",
    "format_suite_json",
    "format_suite_markdown",
    "format_suite_text",
    "glob_search",
    "grep_search",
    "infer_github_repo_from_local",
    "load_config",
    "read_file_with_line_numbers",
    "run_harness_loop",
    "run_harness_session",
    "run_harness_suite",
    "resume_harness_session",
    "run_task_session",
    "serialize_session_result",
    "serialize_suite_result",
    "validate_task_request",
]
