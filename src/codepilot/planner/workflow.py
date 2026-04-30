"""Planning workflow primitives for plan-execute interaction."""

from __future__ import annotations

from dataclasses import dataclass

from codepilot.core.models import validate_task_request
from codepilot.safety.guard import RiskAssessment, evaluate_operation_risk
from codepilot.tools.capabilities import ToolCapability
from codepilot.workspace.inspector import WorkspaceProfile


@dataclass(frozen=True, slots=True)
class PlanStartResponse:  # pylint: disable=too-many-instance-attributes
    """High-level result returned after the plan phase completes."""

    status: str
    can_execute: bool
    next_action: str
    summary: str
    steps: tuple[str, ...]
    candidate_files: list[str]
    candidate_commands: list[str]
    risk: RiskAssessment
    user_options: list[str]


class PlanExecutionController:
    """Coordinates the plan-first workflow before any code execution occurs."""

    def __init__(self, capabilities: tuple[ToolCapability, ...]) -> None:
        self.capabilities = capabilities

    def start_task(
        self,
        description: str,
        workdir: str,
        mode: str,
        *,
        workspace_profile: WorkspaceProfile | None = None,
    ) -> PlanStartResponse:
        """Validate input and decide whether to stop after planning or continue."""
        request = validate_task_request(description, workdir, mode)
        capability_count = len(self.capabilities)
        steps = (
            "Inspect repository structure and key context",
            "Select the files and commands required for the task",
            "Prepare an execution plan with visible boundaries",
            "Review risks and require confirmation before risky changes",
        )
        candidate_files = (
            workspace_profile.candidate_files
            if workspace_profile is not None
            else [
                f"{request.workdir}/README.md",
                f"{request.workdir}/src/app.py",
                f"{request.workdir}/tests/",
            ]
        )
        candidate_commands = (
            workspace_profile.candidate_commands
            if workspace_profile is not None
            else ["pytest -q", "ruff check ."]
        )
        risk = evaluate_operation_risk(request.description)
        workspace_summary = ""
        if workspace_profile is not None:
            workspace_summary = f" Workspace summary: {workspace_profile.summary}"
        summary = (
            f"Generated a plan for '{request.description}' using {capability_count} core tools. "
            f"Current mode: {request.mode}.{workspace_summary}"
        )
        if request.mode == "plan":
            return PlanStartResponse(
                status="awaiting_confirmation",
                can_execute=False,
                next_action="wait_for_user_confirmation",
                summary=summary,
                steps=steps,
                candidate_files=candidate_files,
                candidate_commands=candidate_commands,
                risk=risk,
                user_options=[
                    "continue_discussing_plan",
                    "confirm_execution",
                    "cancel_task",
                ],
            )
        return PlanStartResponse(
            status="ready_to_execute",
            can_execute=True,
            next_action="execute_plan",
            summary=summary,
            steps=steps,
            candidate_files=candidate_files,
            candidate_commands=candidate_commands,
            risk=risk,
            user_options=["execute_plan"],
        )
