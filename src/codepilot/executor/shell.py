"""Shell execution helpers for Sprint 1."""

from __future__ import annotations

import os
import shlex
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
        self.cwd = Path(workdir).expanduser().resolve()
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
        self._update_cwd_from_command(command, completed.returncode, self.cwd)
        stdout = _truncate_output(completed.stdout, self.max_output_lines)
        stderr = _truncate_output(completed.stderr, self.max_output_lines)
        return ShellCommandResult(
            command=command,
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def _update_cwd_from_command(self, command: str, exit_code: int, base_cwd: Path) -> None:
        target = _extract_leading_cd_target(command, base_cwd)
        if target is None:
            return
        if not target.exists():
            return
        if exit_code != 0 and not _command_contains_followup_after_cd(command):
            return
        self.cwd = target.resolve()


def _extract_leading_cd_target(command: str, base_cwd: Path) -> Path | None:
    stripped = command.strip()
    if not stripped.startswith("cd "):
        return None
    head = stripped
    for separator in ("&&", ";", "||"):
        if separator in head:
            head = head.split(separator, maxsplit=1)[0].strip()
            break
    try:
        parts = shlex.split(head)
    except ValueError:
        return None
    if len(parts) < 2 or parts[0] != "cd":
        return None
    candidate = Path(parts[1]).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base_cwd / candidate).resolve()


def _command_contains_followup_after_cd(command: str) -> bool:
    stripped = command.strip()
    return any(separator in stripped for separator in ("&&", ";", "||"))


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
