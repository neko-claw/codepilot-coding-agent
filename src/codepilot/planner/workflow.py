"""Planning workflow primitives for plan-execute interaction."""

from dataclasses import dataclass

from codepilot.core.models import validate_task_request
from codepilot.tools.capabilities import ToolCapability


@dataclass(frozen=True, slots=True)
class PlanStartResponse:
    """High-level result returned after the plan phase completes."""

    status: str
    can_execute: bool
    next_action: str
    summary: str


class PlanExecutionController:
    """Coordinates the plan-first workflow before any code execution occurs."""

    def __init__(self, capabilities: tuple[ToolCapability, ...]) -> None:
        self.capabilities = capabilities

    def start_task(self, description: str, workdir: str, mode: str) -> PlanStartResponse:
        """Validate input and decide whether to stop after planning or continue."""
        request = validate_task_request(description, workdir, mode)
        capability_count = len(self.capabilities)
        summary = (
            f"Generated a plan for '{request.description}' using {capability_count} core tools. "
            f"Current mode: {request.mode}."
        )
        if request.mode == "plan":
            return PlanStartResponse(
                status="awaiting_confirmation",
                can_execute=False,
                next_action="wait_for_user_confirmation",
                summary=summary,
            )
        return PlanStartResponse(
            status="ready_to_execute",
            can_execute=True,
            next_action="execute_plan",
            summary=summary,
        )
