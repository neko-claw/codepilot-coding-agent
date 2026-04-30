from __future__ import annotations

import json
from pathlib import Path

from codepilot.eval import load_benchmark_cases, supported_dataset_formats


def test_load_benchmark_cases_detects_apps_jsonl(tmp_path: Path) -> None:
    dataset_path = tmp_path / "apps.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "problem_id": "apps-001",
                "question": "Implement a function that returns the square of a number.",
                "entry_point": "square",
                "starter_code": "def square(x):\n    pass\n",
                "test_list": ["assert square(4) == 16"],
                "expected_summary_contains": ["square", "number"],
            }
        ),
        encoding="utf-8",
    )

    cases = load_benchmark_cases(dataset_path)

    assert "apps" in supported_dataset_formats()
    assert len(cases) == 1
    case = cases[0]
    assert case.name == "apps-001"
    assert "square" in case.prompt
    assert "returns the square" in case.prompt
    assert case.seed_files["src/square.py"].startswith("def square")
    assert case.seed_files["tests/test_square.py"].startswith("import sys")
    assert case.expected_candidate_files == ("src/square.py", "tests/test_square.py")
    assert case.expected_summary_contains == ("square", "number")
