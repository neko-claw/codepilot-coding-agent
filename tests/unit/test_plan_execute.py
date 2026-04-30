from pathlib import Path

import pytest

from codepilot.planner.workflow import PlanExecutionController
from codepilot.tools.capabilities import default_capability_set
from codepilot.workspace.inspector import inspect_workspace


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


def test_plan_controller_uses_workspace_profile_for_realistic_candidates(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tests_dir / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    controller = PlanExecutionController(default_capability_set())
    response = controller.start_task(
        description="修复测试并检查质量门禁",
        workdir=str(tmp_path),
        mode="plan",
        workspace_profile=inspect_workspace(tmp_path, "修复测试并检查质量门禁"),
    )

    assert any(path.endswith("tests/test_app.py") for path in response.candidate_files)
    assert response.candidate_commands[:2] == ["pytest -q", "ruff check ."]


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
