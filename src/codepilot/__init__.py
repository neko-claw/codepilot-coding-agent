"""CodePilot package."""

from .core.models import TaskRequest, validate_task_request
from .executor.interpreter import PythonExecutionResult, execute_python
from .executor.shell import PersistentShellSession, ShellCommandResult
from .planner.workflow import PlanExecutionController, PlanStartResponse
from .safety.guard import evaluate_operation_risk
from .tools.capabilities import ToolCapability, default_capability_set
from .tools.filesystem import (
    FileEditResult,
    FileReadResult,
    edit_file_by_replacement,
    read_file_with_line_numbers,
)
from .tools.search import glob_search, grep_search

__all__ = [
    "TaskRequest",
    "ToolCapability",
    "FileEditResult",
    "FileReadResult",
    "PersistentShellSession",
    "PythonExecutionResult",
    "ShellCommandResult",
    "PlanExecutionController",
    "PlanStartResponse",
    "default_capability_set",
    "edit_file_by_replacement",
    "execute_python",
    "glob_search",
    "grep_search",
    "read_file_with_line_numbers",
    "validate_task_request",
    "evaluate_operation_risk",
]
