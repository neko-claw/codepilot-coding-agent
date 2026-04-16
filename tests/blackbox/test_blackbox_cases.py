import pytest

from codepilot.core.models import (
    MAX_TASK_LENGTH,
    MAX_WORKDIR_LENGTH,
    ValidationError,
    validate_task_request,
)
from codepilot.safety.guard import evaluate_operation_risk


@pytest.mark.parametrize(
    ("description", "workdir", "mode"),
    [
        ("新增注册接口", "/repo", "plan"),
        ("修复登录 bug", "/repo", "auto"),
    ],
)
def test_blackbox_valid_equivalence_classes(description: str, workdir: str, mode: str) -> None:
    result = validate_task_request(description, workdir, mode)
    assert result.description == description
    assert result.workdir == workdir
    assert result.mode == mode


@pytest.mark.parametrize(
    ("description", "workdir", "mode", "message"),
    [
        ("", "/repo", "plan", "任务描述不能为空"),
        ("x" * (MAX_TASK_LENGTH + 1), "/repo", "plan", str(MAX_TASK_LENGTH)),
        ("新增接口", "", "plan", "工作目录不能为空"),
        ("新增接口", "x" * (MAX_WORKDIR_LENGTH + 1), "plan", str(MAX_WORKDIR_LENGTH)),
        ("新增接口", "/repo", "run", "plan 或 auto"),
    ],
)
def test_blackbox_invalid_equivalence_classes(
    description: str,
    workdir: str,
    mode: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        validate_task_request(description, workdir, mode)


@pytest.mark.parametrize(
    ("description", "workdir", "should_pass"),
    [
        ("", "/r", False),
        ("a", "/r", True),
        ("a" * MAX_TASK_LENGTH, "/r", True),
        ("a" * (MAX_TASK_LENGTH + 1), "/r", False),
        ("ok", "", False),
        ("ok", "/", True),
        ("ok", "a" * MAX_WORKDIR_LENGTH, True),
        ("ok", "a" * (MAX_WORKDIR_LENGTH + 1), False),
    ],
)
def test_blackbox_boundary_values(description: str, workdir: str, should_pass: bool) -> None:
    if should_pass:
        result = validate_task_request(description, workdir, "plan")
        assert result.description == description.strip()
    else:
        with pytest.raises(ValidationError):
            validate_task_request(description, workdir, "plan")


@pytest.mark.parametrize(
    ("plan_text", "expected_level"),
    [
        ("rm -rf /tmp/project", "high"),
        ("overwrite existing config", "medium"),
        ("add tests only", "low"),
    ],
)
def test_blackbox_risk_levels(plan_text: str, expected_level: str) -> None:
    result = evaluate_operation_risk(plan_text)
    assert result.level == expected_level
