from pathlib import Path

import pytest

from codepilot.runtime.session import run_task_session


class _FakePlannerClient:
    def generate_plan(self, task_description: str, workdir: str, capabilities: tuple[str, ...]):
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": f"LLM plan for {task_description}",
                "steps": ("Read files", "Run tests"),
                "candidate_commands": ["pytest -q"],
            },
        )()


def test_run_task_session_uses_planner_client_output(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    result = run_task_session(
        description="补充失败测试的修复计划",
        workdir=tmp_path,
        mode="plan",
        planner_client=_FakePlannerClient(),
    )

    assert result.plan.summary == "LLM plan for 补充失败测试的修复计划"
    assert result.plan.steps == ("Read files", "Run tests")
    assert result.plan.candidate_commands == ["pytest -q"]


def test_run_task_session_rejects_commands_outside_allowlist(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text(
        "def test_demo():\n    assert True\n",
        encoding="utf-8",
    )

    with pytest.raises(PermissionError, match="allowlist"):
        run_task_session(
            description="验证当前仓库测试是否通过",
            workdir=tmp_path,
            mode="auto",
            command_allowlist=("python -m pytest -q",),
            strict_command_allowlist=True,
        )
