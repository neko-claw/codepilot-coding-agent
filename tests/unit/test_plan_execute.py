import pytest

from codepilot.planner.workflow import PlanExecutionController
from codepilot.tools.capabilities import default_capability_set


def test_plan_mode_requires_user_confirmation_before_execution() -> None:
    controller = PlanExecutionController(default_capability_set())

    response = controller.start_task(
        description="为 Flask 项目新增注册接口",
        workdir="/repo",
        mode="plan",
    )

    assert response.status == "awaiting_confirmation"
    assert response.can_execute is False
    assert response.next_action == "wait_for_user_confirmation"
    assert "plan" in response.summary.lower()
    assert response.steps
    assert response.candidate_files == ["/repo/README.md", "/repo/src/app.py", "/repo/tests/"]
    assert response.candidate_commands == ["pytest -q", "ruff check ."]
    assert response.risk.level == "low"
    assert response.user_options == [
        "continue_discussing_plan",
        "confirm_execution",
        "cancel_task",
    ]


def test_auto_mode_can_continue_after_plan_generation() -> None:
    controller = PlanExecutionController(default_capability_set())

    response = controller.start_task(
        description="修复登录测试",
        workdir="/repo",
        mode="auto",
    )

    assert response.status == "ready_to_execute"
    assert response.can_execute is True
    assert response.next_action == "execute_plan"
    assert response.user_options == ["execute_plan"]


def test_plan_mode_marks_risky_requests_for_confirmation() -> None:
    controller = PlanExecutionController(default_capability_set())

    response = controller.start_task(
        description="删除旧数据库并重新初始化",
        workdir="/repo",
        mode="plan",
    )

    assert response.risk.level == "high"
    assert response.risk.requires_confirmation is True
    assert "delete" in response.risk.reason.lower()


@pytest.mark.parametrize(
    "required_tool",
    [
        "code_interpreter",
        "bash_shell",
        "read_file",
        "write_file",
        "edit_file",
        "glob_search",
        "grep_search",
    ],
)
def test_default_capability_set_contains_required_agent_tools(required_tool: str) -> None:
    capability_names = {capability.name for capability in default_capability_set()}
    assert required_tool in capability_names
