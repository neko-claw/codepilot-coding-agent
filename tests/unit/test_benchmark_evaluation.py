from __future__ import annotations

from pathlib import Path

from codepilot.eval.benchmark import load_benchmark_cases, run_benchmark_case


class _BenchmarkPlannerClient:
    def generate_plan(
        self, task_description: str, workdir: str, capabilities: tuple[str, ...], **kwargs
    ):
        has_agent_prompt = "agent" in task_description.lower()
        has_existing_repo = bool(kwargs.get("candidate_files")) and any(
            path.endswith("README.md") for path in kwargs.get("candidate_files", ())
        )
        if has_agent_prompt:
            return type(
                "PlanSuggestion",
                (),
                {
                    "summary": "Generate an agent scaffold",
                    "steps": ("Create agent", "Create CLI", "Create tests"),
                    "candidate_commands": ["pytest -q"],
                    "file_reads": ["src/agent.py", "src/cli.py", "tests/test_agent.py"],
                    "file_edits": [],
                    "file_writes": [
                        type(
                            "FileWrite",
                            (),
                            {"path": "src/agent.py", "content": "class Agent:\n    pass\n"},
                        )(),
                        type(
                            "FileWrite",
                            (),
                            {"path": "src/cli.py", "content": "def main():\n    return 0\n"},
                        )(),
                        type(
                            "FileWrite",
                            (),
                            {"path": "src/__init__.py", "content": "from .agent import Agent\n"},
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
                                    "def test_agent():\n"
                                    "    assert Agent() is not None\n"
                                ),
                            },
                        )(),
                    ],
                },
            )()
        if has_existing_repo:
            return type(
                "PlanSuggestion",
                (),
                {
                    "summary": "Understand the existing repository",
                    "steps": ("Read README", "Read tests", "Confirm workflow"),
                    "candidate_commands": ["pytest -q"],
                    "file_reads": ["README.md", "tests/test_app.py", "src/app.py"],
                    "file_edits": [],
                    "file_writes": [],
                },
            )()
        return type(
            "PlanSuggestion",
            (),
            {
                "summary": "Fallback plan",
                "steps": ("Inspect workspace",),
                "candidate_commands": ["pytest -q"],
                "file_reads": ["README.md"],
                "file_edits": [],
                "file_writes": [],
            },
        )()


def test_benchmark_loader_and_runner_support_agent_bootstrap_and_repo_comprehension(
    tmp_path: Path,
) -> None:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "coding_benchmark_suite.json"
    cases = load_benchmark_cases(fixture_path)

    assert [case.name for case in cases] == ["agent_bootstrap", "repo_comprehension"]

    bootstrap_case = cases[0]
    bootstrap_result = run_benchmark_case(bootstrap_case, _BenchmarkPlannerClient())
    assert bootstrap_result.passed is True
    assert bootstrap_result.result is not None
    assert (tmp_path / "unused").exists() is False
    assert any("src/agent.py" in item for item in bootstrap_result.observations)

    repo_case = cases[1]
    repo_result = run_benchmark_case(repo_case, _BenchmarkPlannerClient())
    assert repo_result.passed is True
    assert repo_result.result is not None
    assert any("README.md" in item for item in repo_result.observations)
    assert any("tests/test_app.py" in item for item in repo_result.observations)
