from pathlib import Path

import pytest

from codepilot.runtime.session import run_task_session


class _FakePlannerClient:
    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": f"LLM plan for {task_description}",
                "steps": ("Read files", "Run tests"),
                "candidate_commands": ["pytest -q"],
                "file_reads": ["README.md"],
                "file_edits": [],
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
    assert result.planner_trace[0].source == "deepseek"
    assert any(path.endswith("README.md") for path in result.inspected_files)


class _FailingPlannerClient:
    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        raise TimeoutError("The read operation timed out")


def test_run_task_session_falls_back_to_workspace_plan_when_planner_times_out(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = run_task_session(
        description="为当前仓库生成修复计划",
        workdir=tmp_path,
        mode="plan",
        planner_client=_FailingPlannerClient(),
    )

    assert result.planner_trace[0].source == "fallback"
    assert "Planner fallback activated" in result.plan.summary
    assert any("回退到本地工作区规划" in hint for hint in result.failure_hints)


class _UnsafePlannerClient:
    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": f"LLM plan for {task_description}",
                "steps": ("Inspect repo", "Run custom script"),
                "candidate_commands": ["rm -rf .", "python dangerous.py"],
                "file_reads": ["README.md"],
                "file_edits": [],
            },
        )()


def test_run_task_session_filters_unsafe_planner_commands(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = run_task_session(
        description="验证当前仓库测试是否通过",
        workdir=tmp_path,
        mode="plan",
        planner_client=_UnsafePlannerClient(),
    )

    assert result.plan.candidate_commands == ["pytest -q", "ruff check ."]


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


class _EditingPlannerClient:
    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": f"LLM plan for {task_description}",
                "steps": ("Inspect failing implementation", "Apply fix", "Run tests"),
                "candidate_commands": ["pytest -q"],
                "file_reads": ["src/app.py", "tests/test_app.py"],
                "file_edits": [
                    type(
                        "FileEdit",
                        (),
                        {
                            "path": "src/app.py",
                            "old_string": "return a - b",
                            "new_string": "return a + b",
                            "replace_all": False,
                        },
                    )()
                ],
            },
        )()


class _BrokenEditPlannerClient:
    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": f"LLM plan for {task_description}",
                "steps": ("Break file", "Run tests"),
                "candidate_commands": ["pytest -q"],
                "file_reads": ["src/app.py"],
                "file_edits": [
                    type(
                        "FileEdit",
                        (),
                        {
                            "path": "src/app.py",
                            "old_string": "return a + b",
                            "new_string": "return (",
                            "replace_all": False,
                        },
                    )()
                ],
            },
        )()


class _ScaffoldPlannerClient:
    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": f"LLM plan for {task_description}",
                "steps": ("Create implementation", "Create tests", "Run tests"),
                "candidate_commands": ["pytest -q"],
                "file_reads": ["src/app.py", "tests/test_app.py"],
                "file_edits": [],
                "file_writes": [
                    type(
                        "FileWrite",
                        (),
                        {
                            "path": "src/app.py",
                            "content": "def add(a, b):\n    return a + b\n",
                        },
                    )(),
                    type(
                        "FileWrite",
                        (),
                        {
                            "path": "src/__init__.py",
                            "content": "",
                        },
                    )(),
                    type(
                        "FileWrite",
                        (),
                        {
                            "path": "tests/test_app.py",
                            "content": (
                                "import sys\nfrom pathlib import Path\n\n"
                                "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
                                "from src.app import add\n\n"
                                "def test_add():\n"
                                "    assert add(1, 2) == 3\n"
                            ),
                        },
                    )(),
                ],
            },
        )()


class _AgentScaffoldPlannerClient:
    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": f"LLM plan for {task_description}",
                "steps": ("Create agent scaffold", "Create tests", "Run tests"),
                "candidate_commands": ["pytest -q"],
                "file_reads": ["src/agent.py", "src/cli.py", "tests/test_agent.py"],
                "file_edits": [],
                "file_writes": [
                    type(
                        "FileWrite",
                        (),
                        {
                            "path": "src/agent.py",
                            "content": (
                                "class Agent:\n"
                                "    def __init__(self, name: str = 'CodePilot') -> None:\n"
                                "        self.name = name\n\n"
                                "    def respond(self, prompt: str) -> str:\n"
                                "        return f'{self.name}: {prompt}'\n"
                            ),
                        },
                    )(),
                    type(
                        "FileWrite",
                        (),
                        {
                            "path": "src/cli.py",
                            "content": (
                                "from __future__ import annotations\n\n"
                                "import argparse\n\n"
                                "from .agent import Agent\n\n\n"
                                "def main(argv: list[str] | None = None) -> int:\n"
                                "    parser = argparse.ArgumentParser()\n"
                                "    parser.add_argument('prompt')\n"
                                "    args = parser.parse_args(argv)\n"
                                "    print(Agent().respond(args.prompt))\n"
                                "    return 0\n"
                            ),
                        },
                    )(),
                    type(
                        "FileWrite",
                        (),
                        {
                            "path": "src/__init__.py",
                            "content": "from .agent import Agent\n",
                        },
                    )(),
                    type(
                        "FileWrite",
                        (),
                        {
                            "path": "tests/test_agent.py",
                            "content": (
                                "import sys\nfrom pathlib import Path\n\n"
                                "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
                                "from src.agent import Agent\n\n\n"
                                "def test_agent_responds_with_prompt():\n"
                                "    assert Agent().respond('build me an agent') == "
                                "'CodePilot: build me an agent'\n"
                            ),
                        },
                    )(),
                ],
            },
        )()


class _EnvironmentFailurePlannerClient:
    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": f"LLM plan for {task_description}",
                "steps": ("Run unavailable tool",),
                "candidate_commands": ["python -m missing_tool"],
                "file_reads": ["README.md"],
                "file_edits": [],
            },
        )()


def test_run_task_session_does_not_retry_environment_failures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    planner = _EnvironmentFailurePlannerClient()
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    monkeypatch.setattr(
        "codepilot.runtime.session._execute_allowed_commands",
        lambda *args, **kwargs: [
            type(
                "Result",
                (),
                {
                    "command": "python -m missing_tool",
                    "exit_code": 127,
                    "stdout": "",
                    "stderr": "/bin/bash: python -m missing_tool: command not found",
                },
            )()
        ],
    )

    result = run_task_session(
        description="执行一个不存在的工具",
        workdir=tmp_path,
        mode="auto",
        planner_client=planner,
    )

    assert len(result.retry_trace) == 1
    assert result.retry_trace[0].failure_type == "environment_error"
    assert result.retry_trace[0].retried is False
    assert any("环境级失败" in hint for hint in result.failure_hints)


class _RetryingPlannerClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        self.calls.append(kwargs)
        has_failure_context = bool(kwargs.get("failure_context"))
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": "Retry plan" if has_failure_context else "Initial plan",
                "steps": ("Inspect implementation", "Apply fix", "Run tests"),
                "candidate_commands": ["pytest -q"],
                "file_reads": ["src/app.py", "tests/test_app.py"],
                "file_edits": [
                    type(
                        "FileEdit",
                        (),
                        {
                            "path": "src/app.py",
                            "old_string": "return a * b" if has_failure_context else "return a - b",
                            "new_string": "return a + b" if has_failure_context else "return a * b",
                            "replace_all": False,
                        },
                    )()
                ],
            },
        )()


class _EditFailureRecoveringPlannerClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        self.calls.append(kwargs)
        has_failure_context = bool(kwargs.get("failure_context"))
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": "Retry after edit failure"
                if has_failure_context
                else "Initial ambiguous edit",
                "steps": ("Inspect implementation", "Apply fix", "Run tests"),
                "candidate_commands": ["pytest -q"],
                "file_reads": ["src/app.py", "tests/test_app.py"],
                "file_edits": [
                    type(
                        "FileEdit",
                        (),
                        {
                            "path": "src/app.py",
                            "old_string": "return a - b\n" if has_failure_context else "a",
                            "new_string": "return a + b\n",
                            "replace_all": False,
                        },
                    )()
                ],
            },
        )()


class _SyntaxFailureRecoveringPlannerClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_plan(
        self,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        **kwargs,
    ):
        self.calls.append(kwargs)
        has_failure_context = bool(kwargs.get("failure_context"))
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": "Retry after syntax failure"
                if has_failure_context
                else "Initial syntax-sensitive plan",
                "steps": ("Inspect implementation", "Repair syntax issue", "Run tests"),
                "candidate_commands": ["python -m pytest -q"],
                "file_reads": ["src/app.py", "tests/test_app.py"],
                "file_edits": [],
            },
        )()


def test_run_task_session_auto_mode_applies_planner_file_edits_and_verifies(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (src_dir / "app.py").write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (tests_dir / "test_app.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "from src.app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )

    result = run_task_session(
        description="修复 add 的失败测试",
        workdir=tmp_path,
        mode="auto",
        planner_client=_EditingPlannerClient(),
        command_allowlist=("pytest -q",),
    )

    assert len(result.edit_results) == 1
    assert result.edit_results[0].applied is True
    assert result.edit_results[0].reverted is False
    assert result.edit_results[0].path.endswith("src/app.py")
    assert result.command_results[0].exit_code == 0
    assert "return a + b" in (src_dir / "app.py").read_text(encoding="utf-8")


def test_run_task_session_creates_new_agent_files_from_planner_writes(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    result = run_task_session(
        description="从零创建一个可用的 coding agent",
        workdir=tmp_path,
        mode="auto",
        planner_client=_AgentScaffoldPlannerClient(),
        command_allowlist=("pytest -q",),
    )

    assert len(result.edit_results) == 4
    assert {Path(item.path).name for item in result.edit_results} == {
        "agent.py",
        "cli.py",
        "__init__.py",
        "test_agent.py",
    }
    assert all(item.applied is True for item in result.edit_results)
    assert result.command_results[0].exit_code == 0
    assert (tmp_path / "src" / "agent.py").read_text(encoding="utf-8").startswith("class Agent")
    assert "CodePilot: build me an agent" in (tmp_path / "tests" / "test_agent.py").read_text(
        encoding="utf-8"
    )


def test_run_task_session_passes_bootstrap_candidates_to_planner(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _CapturePlannerClient:
        def generate_plan(
            self, task_description: str, workdir: str, capabilities: tuple[str, ...], **kwargs
        ):
            captured.update(kwargs)
            return type(
                "PlanSuggestion",
                (),
                {
                    "summary": f"LLM plan for {task_description}",
                    "steps": ("Create scaffold",),
                    "candidate_commands": ["pytest -q"],
                    "file_reads": ["src/app.py", "tests/test_app.py"],
                    "file_edits": [],
                    "file_writes": [],
                },
            )()

    run_task_session(
        description="从零创建一个 Python 项目",
        workdir=tmp_path,
        mode="plan",
        planner_client=_CapturePlannerClient(),
    )

    assert any(path.endswith("src/app.py") for path in captured["candidate_files"])
    assert any(path.endswith("tests/test_app.py") for path in captured["candidate_files"])


def test_run_task_session_reverts_syntax_broken_planner_edit(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    target = src_dir / "app.py"
    original_text = "def add(a, b):\n    return a + b\n"
    target.write_text(original_text, encoding="utf-8")
    (tests_dir / "test_app.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "from src.app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )

    result = run_task_session(
        description="尝试修复 add 的测试",
        workdir=tmp_path,
        mode="auto",
        planner_client=_BrokenEditPlannerClient(),
        command_allowlist=("pytest -q",),
        max_auto_retries=0,
    )

    assert len(result.edit_results) == 1
    assert result.edit_results[0].applied is False
    assert result.edit_results[0].reverted is True
    assert result.edit_results[0].syntax_check.startswith("error:")
    assert target.read_text(encoding="utf-8") == original_text
    assert any("语法" in hint for hint in result.failure_hints)


def test_run_task_session_records_failure_target_files_for_retry_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    planner_calls: list[dict[str, object]] = []
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("def test_add():\n    assert True\n", encoding="utf-8")

    monkeypatch.setattr(
        "codepilot.runtime.session._execute_allowed_commands",
        lambda *args, **kwargs: [
            type(
                "Result",
                (),
                {
                    "command": "pytest -q",
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": f"AssertionError: failure in {tmp_path / 'src' / 'app.py'}",
                },
            )()
        ],
    )

    class _CapturePlannerClient:
        def generate_plan(
            self,
            task_description: str,
            workdir: str,
            capabilities: tuple[str, ...],
            **kwargs,
        ):
            planner_calls.append(kwargs)
            return type(
                "PlanSuggestion",
                (),
                {
                    "summary": f"LLM plan for {task_description}",
                    "steps": ("Inspect", "Fix", "Verify"),
                    "candidate_commands": ["pytest -q"],
                    "file_reads": ["src/app.py", "tests/test_app.py"],
                    "file_edits": [],
                    "file_writes": [],
                },
            )()

    run_task_session(
        description="修复 add 的失败测试",
        workdir=tmp_path,
        mode="auto",
        planner_client=_CapturePlannerClient(),
        command_allowlist=("pytest -q",),
    )

    assert len(planner_calls) == 2
    assert planner_calls[1]["failure_context"]
    assert planner_calls[1]["failure_context"][0]["target_files"]
    assert any(
        str(tmp_path / "src" / "app.py") in item
        for item in planner_calls[1]["failure_context"][0]["target_files"]
    )


def test_run_task_session_retries_on_syntax_failure_and_recovers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    planner = _SyntaxFailureRecoveringPlannerClient()
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    target = src_dir / "app.py"
    target.write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )
    (tests_dir / "test_app.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "from src.app import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    call_count = {"count": 0}

    def _execute_allowed_commands(*args, **kwargs):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return [
                type(
                    "Result",
                    (),
                    {
                        "command": "python -m pytest -q",
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": f"SyntaxError: invalid syntax in {target}",
                    },
                )()
            ]
        return [
            type(
                "Result",
                (),
                {
                    "command": "python -m pytest -q",
                    "exit_code": 0,
                    "stdout": "1 passed",
                    "stderr": "",
                },
            )()
        ]

    monkeypatch.setattr(
        "codepilot.runtime.session._execute_allowed_commands", _execute_allowed_commands
    )

    result = run_task_session(
        description="修复 add 的失败测试",
        workdir=tmp_path,
        mode="auto",
        planner_client=planner,
        command_allowlist=("python -m pytest -q",),
    )

    assert len(planner.calls) == 2
    assert planner.calls[1]["failure_context"]
    assert planner.calls[1]["failure_context"][0]["failure_type"] == "syntax_error"
    assert result.retry_trace[0].failure_type == "syntax_error"
    assert result.retry_trace[0].retried is True
    assert result.command_results[-1].exit_code == 0
    assert any("语法" in hint for hint in result.failure_hints)
    assert "return a + b" in target.read_text(encoding="utf-8")


def test_run_task_session_retries_with_failure_context_and_recovers(tmp_path: Path) -> None:
    planner = _RetryingPlannerClient()
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    target = src_dir / "app.py"
    target.write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (tests_dir / "test_app.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "from src.app import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    result = run_task_session(
        description="修复 add 的失败测试",
        workdir=tmp_path,
        mode="auto",
        planner_client=planner,
        command_allowlist=("pytest -q",),
    )

    assert len(planner.calls) == 2
    assert planner.calls[0].get("failure_context") in (None, [])
    assert planner.calls[1]["failure_context"]
    assert planner.calls[1]["failure_context"][0]["failure_type"] == "assertion_failure"
    assert result.retry_trace[0].failure_type == "assertion_failure"
    assert result.retry_trace[0].retried is True
    assert result.command_results[-1].exit_code == 0
    assert "return a + b" in target.read_text(encoding="utf-8")


def test_run_task_session_stops_after_retry_budget_exhausted(tmp_path: Path) -> None:
    planner = _RetryingPlannerClient()
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    target = src_dir / "app.py"
    target.write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (tests_dir / "test_app.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "from src.app import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    result = run_task_session(
        description="修复 add 的失败测试",
        workdir=tmp_path,
        mode="auto",
        planner_client=planner,
        command_allowlist=("pytest -q",),
        max_auto_retries=0,
    )

    assert len(planner.calls) == 1
    assert result.retry_trace[0].failure_type == "assertion_failure"
    assert result.retry_trace[0].retried is False
    assert result.command_results[-1].exit_code != 0
    assert "return a * b" in target.read_text(encoding="utf-8")


def test_run_task_session_retries_after_edit_application_failure_and_recovers(
    tmp_path: Path,
) -> None:
    planner = _EditFailureRecoveringPlannerClient()
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    target = src_dir / "app.py"
    target.write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (tests_dir / "test_app.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "from src.app import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    result = run_task_session(
        description="修复 add 的失败测试",
        workdir=tmp_path,
        mode="auto",
        planner_client=planner,
        command_allowlist=("pytest -q",),
    )

    assert len(planner.calls) == 2
    assert result.retry_trace[0].failure_type == "edit_application_failure"
    assert result.retry_trace[0].retried is True
    assert any("自动修改未能应用" in hint for hint in result.failure_hints)
    assert result.command_results[-1].exit_code == 0
    assert "return a + b" in target.read_text(encoding="utf-8")
