"""Core data models for the CodePilot prototype."""

from dataclasses import dataclass

ALLOWED_MODES = {"plan", "auto"}
MAX_TASK_LENGTH = 500
MAX_WORKDIR_LENGTH = 200


class ValidationError(ValueError):
    """Raised when a task request violates input constraints."""


@dataclass(slots=True)
class TaskRequest:
    """Represents a normalized task submitted by the user."""

    description: str
    workdir: str
    mode: str = "plan"


def validate_task_request(description: str, workdir: str, mode: str = "plan") -> TaskRequest:
    """Validate raw input and return a normalized task request object."""
    normalized_description = description.strip()
    normalized_workdir = workdir.strip()
    normalized_mode = mode.strip().lower()

    if not normalized_description:
        raise ValidationError("任务描述不能为空")
    if len(normalized_description) > MAX_TASK_LENGTH:
        raise ValidationError(f"任务描述不能超过 {MAX_TASK_LENGTH} 个字符")
    if not normalized_workdir:
        raise ValidationError("工作目录不能为空")
    if len(normalized_workdir) > MAX_WORKDIR_LENGTH:
        raise ValidationError(f"工作目录不能超过 {MAX_WORKDIR_LENGTH} 个字符")
    if normalized_mode not in ALLOWED_MODES:
        raise ValidationError("执行模式仅支持 plan 或 auto")

    return TaskRequest(
        description=normalized_description,
        workdir=normalized_workdir,
        mode=normalized_mode,
    )
