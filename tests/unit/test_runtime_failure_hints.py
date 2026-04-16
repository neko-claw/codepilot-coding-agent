from pathlib import Path

from codepilot.runtime.session import run_task_session


class _FailingPlannerClient:
    def generate_plan(self, task_description: str, workdir: str, capabilities: tuple[str, ...]):
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": f"LLM plan for {task_description}",
                "steps": ("Run tests",),
                "candidate_commands": ["pytest -q"],
            },
        )()


def test_run_task_session_generates_failure_hints_for_failed_commands(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_failure.py").write_text(
        "def test_failure():\n    assert 1 == 2\n",
        encoding="utf-8",
    )

    result = run_task_session(
        description="验证失败测试并给出修复建议",
        workdir=tmp_path,
        mode="auto",
        planner_client=_FailingPlannerClient(),
        command_allowlist=("pytest -q",),
    )

    assert result.command_results[0].exit_code != 0
    assert any("pytest" in hint for hint in result.failure_hints)
    assert any("断言" in hint or "测试" in hint for hint in result.failure_hints)
