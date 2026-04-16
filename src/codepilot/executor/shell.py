"""Shell execution helpers for Sprint 1."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ShellCommandResult:
    """Result of a shell command."""

    command: str
    exit_code: int
    stdout: str
    stderr: str


class PersistentShellSession:
    """A tiny stateful shell session that remembers cwd and environment."""

    def __init__(
        self,
        *,
        workdir: str | Path,
        env: dict[str, str] | None = None,
        max_output_lines: int = 40,
    ) -> None:
        self.cwd = Path(workdir)
        self.env = dict(os.environ if env is None else env)
        self.max_output_lines = max_output_lines

    def run(self, command: str, timeout: float = 30.0) -> ShellCommandResult:
        """Run a command, preserving working directory when it changes."""
        completed = subprocess.run(
            command,
            shell=True,
            cwd=self.cwd,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
            executable="/bin/bash",
            check=False,
        )
        self._update_cwd_from_command(command)
        stdout = _truncate_output(completed.stdout, self.max_output_lines)
        stderr = _truncate_output(completed.stderr, self.max_output_lines)
        return ShellCommandResult(
            command=command,
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def _update_cwd_from_command(self, command: str) -> None:
        marker = " && pwd"
        if command.strip().startswith("cd ") and marker in command:
            reported = command.split(marker)[0].strip()[3:].strip()
            self.cwd = Path(reported).expanduser().resolve()


def _truncate_output(output: str, max_lines: int) -> str:
    lines = output.splitlines()
    if len(lines) <= max_lines:
        return output
    head_count = max_lines // 2
    tail_count = max_lines - head_count
    head = lines[:head_count]
    tail = lines[-tail_count:]
    return "\n".join(
        head
        + [f"[output truncated: showing first {head_count} and last {tail_count} lines]"]
        + tail
    )
