"""Python code interpreter for Sprint 1."""

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PythonExecutionResult:
    """Result of executing Python code."""

    success: bool
    stdout: str
    stderr: str
    timed_out: bool


def execute_python(code: str, timeout: float = 5.0) -> PythonExecutionResult:
    """Execute Python code in a subprocess with timeout handling."""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return PythonExecutionResult(
            success=False,
            stdout="",
            stderr="Python execution timed out",
            timed_out=True,
        )
    return PythonExecutionResult(
        success=completed.returncode == 0,
        stdout=completed.stdout,
        stderr=completed.stderr,
        timed_out=False,
    )
