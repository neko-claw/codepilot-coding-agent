from __future__ import annotations

import json
from pathlib import Path

from codepilot.eval import load_benchmark_cases, supported_dataset_formats


def test_supported_dataset_formats_include_swebench() -> None:
    formats = supported_dataset_formats()
    assert "swebench" in formats
    assert "apps" in formats


def test_load_benchmark_cases_detects_swebench_jsonl(tmp_path: Path) -> None:
    dataset_path = tmp_path / "swebench.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "instance_id": "django__django-12345",
                "problem_statement": (
                    "Fix the bug in the URL resolver when path converters are nested."
                ),
                "repo": "django/django",
                "base_commit": "deadbeef",
                "seed_files": {
                    "README.md": "Django repo\n",
                    "tests/test_urls.py": "def test_urls():\n    assert True\n",
                },
                "expected_candidate_files": ["README.md", "tests/test_urls.py"],
                "expected_summary_contains": ["URL resolver", "nested"],
            }
        ),
        encoding="utf-8",
    )

    cases = load_benchmark_cases(dataset_path)

    assert len(cases) == 1
    case = cases[0]
    assert case.name == "django__django-12345"
    assert "django/django" in case.prompt
    assert "Fix the bug" in case.prompt
    assert case.seed_files["README.md"] == "Django repo\n"
    assert case.expected_candidate_files == ("README.md", "tests/test_urls.py")
    assert case.expected_summary_contains == ("URL resolver", "nested")
