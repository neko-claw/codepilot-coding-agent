"""Benchmark helpers for coding-agent capability checks."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codepilot.runtime.session import TaskSessionResult, run_task_session

from .adapters import load_benchmark_cases_from_source


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """Structured benchmark case loaded from a JSON fixture."""

    name: str
    prompt: str
    mode: str = "auto"
    seed_files: dict[str, str] = field(default_factory=dict)
    command_allowlist: tuple[str, ...] | None = None
    max_auto_retries: int = 1
    expected_candidate_files: tuple[str, ...] = ()
    expected_inspected_files: tuple[str, ...] = ()
    expected_written_files: tuple[str, ...] = ()
    expected_written_file_contains: dict[str, str] = field(default_factory=dict)
    expected_command_exit_codes: dict[str, int] = field(default_factory=dict)
    expected_summary_contains: tuple[str, ...] = ()
    expected_file_reads: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Evaluation result for a benchmark case."""

    case: BenchmarkCase
    passed: bool
    observations: tuple[str, ...]
    failures: tuple[str, ...]
    result: TaskSessionResult | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkSuiteResult:
    """Aggregate result for a benchmark suite."""

    total: int
    passed: int
    failed: int
    case_results: tuple[BenchmarkResult, ...]


def load_benchmark_cases(path: str | Path) -> list[BenchmarkCase]:
    """Load benchmark cases from a fixture or public dataset export."""
    return load_benchmark_cases_from_source(path)


def run_benchmark_case(case: BenchmarkCase, planner_client: Any) -> BenchmarkResult:
    """Run one benchmark case in an isolated temporary workspace."""
    with tempfile.TemporaryDirectory(prefix=f"codepilot-benchmark-{case.name}-") as tmpdir:
        workdir = Path(tmpdir)
        for relative_path, content in case.seed_files.items():
            target = workdir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        result = run_task_session(
            description=case.prompt,
            workdir=workdir,
            mode=case.mode,
            planner_client=planner_client,
            command_allowlist=case.command_allowlist,
            max_auto_retries=case.max_auto_retries,
        )
        passed, observations, failures = evaluate_benchmark_case(case, result)
        return BenchmarkResult(
            case=case,
            passed=passed,
            observations=tuple(observations),
            failures=tuple(failures),
            result=result,
        )


def run_benchmark_suite(cases: list[BenchmarkCase], planner_client: Any) -> BenchmarkSuiteResult:
    """Run all cases and return aggregate pass/fail data."""
    case_results = tuple(run_benchmark_case(case, planner_client) for case in cases)
    return summarize_benchmark_results(list(case_results))


def summarize_benchmark_results(case_results: list[BenchmarkResult]) -> BenchmarkSuiteResult:
    """Aggregate already-computed benchmark case results without re-running tasks."""
    passed = sum(1 for case_result in case_results if case_result.passed)
    total = len(case_results)
    return BenchmarkSuiteResult(
        total=total,
        passed=passed,
        failed=total - passed,
        case_results=tuple(case_results),
    )


def evaluate_benchmark_case(
    case: BenchmarkCase, result: TaskSessionResult
) -> tuple[bool, list[str], list[str]]:
    """Compare a session result against the benchmark expectations."""
    observations: list[str] = []
    failures: list[str] = []

    _check_contains(
        label="summary",
        actual=result.plan.summary,
        expected_values=case.expected_summary_contains,
        observations=observations,
        failures=failures,
    )
    _check_paths(
        label="candidate_files",
        actual=result.plan.candidate_files,
        expected_values=case.expected_candidate_files,
        observations=observations,
        failures=failures,
    )
    _check_paths(
        label="inspected_files",
        actual=result.inspected_files,
        expected_values=case.expected_inspected_files,
        observations=observations,
        failures=failures,
    )
    _check_paths(
        label="written_files",
        actual=[edit_result.path for edit_result in result.edit_results],
        expected_values=case.expected_written_files,
        observations=observations,
        failures=failures,
    )
    _check_file_contents(result, case, observations, failures)
    _check_command_exit_codes(result, case, observations, failures)
    if case.expected_file_reads:
        actual_file_reads = list(getattr(result.plan, "file_reads", [])) or list(
            result.plan.candidate_files
        )
        _check_paths(
            label="file_reads",
            actual=actual_file_reads,
            expected_values=case.expected_file_reads,
            observations=observations,
            failures=failures,
        )
    passed = not failures
    observations.append(f"passed={passed}")
    return passed, observations, failures


def _check_contains(
    *,
    label: str,
    actual: str,
    expected_values: tuple[str, ...],
    observations: list[str],
    failures: list[str],
) -> None:
    for expected in expected_values:
        if expected.lower() in actual.lower():
            observations.append(f"{label}: contains {expected}")
        else:
            failures.append(f"{label}: missing {expected}")


def _check_paths(
    *,
    label: str,
    actual: list[str],
    expected_values: tuple[str, ...],
    observations: list[str],
    failures: list[str],
) -> None:
    for expected in expected_values:
        if any(_path_matches(candidate, expected) for candidate in actual):
            observations.append(f"{label}: matched {expected}")
        else:
            failures.append(f"{label}: missing {expected}")


def _check_file_contents(
    result: TaskSessionResult,
    case: BenchmarkCase,
    observations: list[str],
    failures: list[str],
) -> None:
    for relative_path, expected_text in case.expected_written_file_contains.items():
        target = Path(result.request.workdir) / relative_path
        if not target.exists():
            failures.append(f"file_contents: missing {relative_path}")
            continue
        actual = target.read_text(encoding="utf-8")
        if expected_text in actual:
            observations.append(f"file_contents: contains {relative_path}")
        else:
            failures.append(f"file_contents: {relative_path} missing expected text")


def _check_command_exit_codes(
    result: TaskSessionResult,
    case: BenchmarkCase,
    observations: list[str],
    failures: list[str],
) -> None:
    actual_exit_codes = {
        command_result.command: command_result.exit_code
        for command_result in result.command_results
    }
    for command, expected_exit_code in case.expected_command_exit_codes.items():
        actual_exit_code = actual_exit_codes.get(command)
        if actual_exit_code == expected_exit_code:
            observations.append(f"command: {command} => {actual_exit_code}")
        else:
            failures.append(
                f"command: {command} expected {expected_exit_code} got {actual_exit_code}"
            )


def _path_matches(candidate: str, expected: str) -> bool:
    candidate_path = Path(candidate)
    return candidate_path.as_posix().endswith(expected)
