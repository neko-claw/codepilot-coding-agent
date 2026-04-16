"""Executor package."""

from .interpreter import PythonExecutionResult, execute_python
from .shell import PersistentShellSession, ShellCommandResult

__all__ = [
    "PersistentShellSession",
    "PythonExecutionResult",
    "ShellCommandResult",
    "execute_python",
]
