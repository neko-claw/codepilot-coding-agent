"""Tool capability metadata for the CodePilot agent."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolCapability:
    """Describes an agent tool and its operational constraints."""

    name: str
    description: str
    requires_isolation: bool
    primary_use: str


def default_capability_set() -> tuple[ToolCapability, ...]:
    """Return the minimum toolset required by the Coding Agent design."""
    return (
        ToolCapability(
            name="code_interpreter",
            description="Execute Python code inside an isolated Python sandbox.",
            requires_isolation=True,
            primary_use="safe_python_execution",
        ),
        ToolCapability(
            name="bash_shell",
            description="Run controlled shell commands for build, test, and file handling.",
            requires_isolation=True,
            primary_use="command_execution",
        ),
        ToolCapability(
            name="read_file",
            description="Read source code, configs, logs, and project documents.",
            requires_isolation=False,
            primary_use="context_reading",
        ),
        ToolCapability(
            name="write_file",
            description="Create new files or fully rewrite existing files.",
            requires_isolation=False,
            primary_use="full_file_write",
        ),
        ToolCapability(
            name="edit_file",
            description="Apply focused partial edits to existing files.",
            requires_isolation=False,
            primary_use="partial_file_edit",
        ),
        ToolCapability(
            name="glob_search",
            description="Locate files by glob patterns such as *.py or **/tests/*.py.",
            requires_isolation=False,
            primary_use="file_discovery",
        ),
        ToolCapability(
            name="grep_search",
            description="Search file contents for functions, config keys, or error strings.",
            requires_isolation=False,
            primary_use="content_search",
        ),
    )
