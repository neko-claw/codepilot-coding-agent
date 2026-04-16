import pytest

from codepilot.core.models import (
    MAX_TASK_LENGTH,
    MAX_WORKDIR_LENGTH,
    ValidationError,
    validate_task_request,
)


def test_validate_task_request_success_plan() -> None:
    result = validate_task_request("  新增注册接口  ", "  /tmp/repo  ", "PLAN")
    assert result.description == "新增注册接口"
    assert result.workdir == "/tmp/repo"
    assert result.mode == "plan"


def test_validate_task_request_rejects_empty_description() -> None:
    with pytest.raises(ValidationError, match="任务描述不能为空"):
        validate_task_request("   ", "/tmp/repo", "plan")


def test_validate_task_request_rejects_too_long_description() -> None:
    with pytest.raises(ValidationError, match=str(MAX_TASK_LENGTH)):
        validate_task_request("a" * (MAX_TASK_LENGTH + 1), "/tmp/repo", "plan")


def test_validate_task_request_rejects_empty_workdir() -> None:
    with pytest.raises(ValidationError, match="工作目录不能为空"):
        validate_task_request("新增接口", "   ", "plan")


def test_validate_task_request_rejects_too_long_workdir() -> None:
    with pytest.raises(ValidationError, match=str(MAX_WORKDIR_LENGTH)):
        validate_task_request("新增接口", "a" * (MAX_WORKDIR_LENGTH + 1), "plan")


def test_validate_task_request_rejects_invalid_mode() -> None:
    with pytest.raises(ValidationError, match="plan 或 auto"):
        validate_task_request("新增接口", "/tmp/repo", "run")
