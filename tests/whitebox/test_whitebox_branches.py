from codepilot.core.models import MAX_TASK_LENGTH, ValidationError, validate_task_request
from codepilot.safety.guard import evaluate_operation_risk


def test_whitebox_validate_task_request_all_branches() -> None:
    branch_cases = [
        ("", "/repo", "plan", "任务描述不能为空"),
        ("a" * (MAX_TASK_LENGTH + 1), "/repo", "plan", "任务描述不能超过"),
        ("任务", "", "plan", "工作目录不能为空"),
        ("任务", "/repo", "run", "执行模式仅支持"),
    ]

    for description, workdir, mode, message in branch_cases:
        try:
            validate_task_request(description, workdir, mode)
        except ValidationError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("预期应进入异常分支")

    result = validate_task_request("任务", "/repo", "auto")
    assert result.mode == "auto"


def test_whitebox_evaluate_operation_risk_all_branches() -> None:
    empty_result = evaluate_operation_risk("")
    assert empty_result.level == "medium"

    high_result = evaluate_operation_risk("delete user data and rm -rf cache")
    assert high_result.level == "high"

    medium_result = evaluate_operation_risk("reset workspace")
    assert medium_result.level == "medium"

    low_result = evaluate_operation_risk("generate docs")
    assert low_result.level == "low"
