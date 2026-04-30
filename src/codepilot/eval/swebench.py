"""SWE-bench style repository-level benchmark runner."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codepilot.runtime.session import run_task_session

from .benchmark import (
    BenchmarkCase,
    BenchmarkSuiteResult,
    evaluate_benchmark_case,
    summarize_benchmark_results,
)


@dataclass(slots=True)
class PreparedSWEBenchWorkspace(AbstractContextManager[Path]):
    """Prepared workspace that keeps temporary state alive until cleanup."""

    path: Path
    _tempdir: tempfile.TemporaryDirectory[str] | None

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.cleanup()
        return False

    def cleanup(self) -> None:
        """Delete the temporary workspace when the caller is done."""
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None


@dataclass(frozen=True, slots=True)
class SWEBenchRunResult:
    """Result for one SWE-bench benchmark case."""

    case: BenchmarkCase
    prepared_workspace: PreparedSWEBenchWorkspace
    session_result: Any

    @property
    def workspace_path(self) -> Path:
        return self.prepared_workspace.path


@dataclass(frozen=True, slots=True)
class SWEBenchSuiteRunResult:
    """Result for running a SWE-bench suite."""

    benchmark_result: BenchmarkSuiteResult
    run_results: tuple[SWEBenchRunResult, ...]


def prepare_swebench_workspace(
    case: BenchmarkCase,
    *,
    source_repo: str | Path | None = None,
    checkout_ref: str | None = None,
) -> PreparedSWEBenchWorkspace:
    """Create an isolated workspace for a SWE-bench case."""
    tempdir = tempfile.TemporaryDirectory(prefix=f"codepilot-swebench-{case.name}-")
    workspace_path = Path(tempdir.name) / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)

    if source_repo is not None:
        _populate_from_source_repo(workspace_path, Path(source_repo), checkout_ref=checkout_ref)

    _apply_seed_files(workspace_path, case.seed_files)
    _write_case_manifest(workspace_path, case, source_repo=source_repo, checkout_ref=checkout_ref)
    return PreparedSWEBenchWorkspace(path=workspace_path, _tempdir=tempdir)


def run_swebench_case(
    case: BenchmarkCase,
    planner_client: Any,
    *,
    source_repo: str | Path | None = None,
    checkout_ref: str | None = None,
) -> SWEBenchRunResult:
    """Run a single SWE-bench case inside a prepared workspace."""
    prepared_workspace = prepare_swebench_workspace(
        case,
        source_repo=source_repo,
        checkout_ref=checkout_ref,
    )
    session_result = run_task_session(
        description=case.prompt,
        workdir=prepared_workspace.path,
        mode=case.mode,
        planner_client=planner_client,
        command_allowlist=case.command_allowlist,
        max_auto_retries=case.max_auto_retries,
    )
    return SWEBenchRunResult(
        case=case,
        prepared_workspace=prepared_workspace,
        session_result=session_result,
    )


def run_swebench_suite(
    cases: list[BenchmarkCase],
    planner_client: Any,
    *,
    source_repo: str | Path | None = None,
    checkout_ref: str | None = None,
) -> SWEBenchSuiteRunResult:
    """Run an entire SWE-bench suite."""
    run_results = tuple(
        run_swebench_case(
            case,
            planner_client,
            source_repo=source_repo,
            checkout_ref=checkout_ref,
        )
        for case in cases
    )
    benchmark_case_results = [
        _build_benchmark_result(run_result.case, run_result.session_result)
        for run_result in run_results
    ]
    benchmark_result = summarize_benchmark_results(benchmark_case_results)
    return SWEBenchSuiteRunResult(benchmark_result=benchmark_result, run_results=run_results)


def _populate_from_source_repo(
    workspace_path: Path,
    source_repo: Path,
    *,
    checkout_ref: str | None,
) -> None:
    if (source_repo / ".").exists() and (source_repo / ".git").exists():
        subprocess.run(
            ["git", "clone", "--quiet", str(source_repo), str(workspace_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        if checkout_ref:
            subprocess.run(
                ["git", "-C", str(workspace_path), "checkout", "--quiet", checkout_ref],
                check=True,
                capture_output=True,
                text=True,
            )
    else:
        shutil.copytree(source_repo, workspace_path, dirs_exist_ok=True)


def _apply_seed_files(workspace_path: Path, seed_files: dict[str, str]) -> None:
    for relative_path, content in seed_files.items():
        target = workspace_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _build_benchmark_result(case: BenchmarkCase, session_result: Any):
    passed, observations, failures = evaluate_benchmark_case(case, session_result)
    from .benchmark import BenchmarkResult

    return BenchmarkResult(
        case=case,
        passed=passed,
        observations=tuple(observations),
        failures=tuple(failures),
        result=session_result,
    )


def _write_case_manifest(
    workspace_path: Path,
    case: BenchmarkCase,
    *,
    source_repo: str | Path | None,
    checkout_ref: str | None,
) -> None:
    codepilot_dir = workspace_path / ".codepilot"
    codepilot_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = codepilot_dir / "swebench-case.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": case.name,
                "prompt": case.prompt,
                "mode": case.mode,
                "command_allowlist": list(case.command_allowlist or ()),
                "max_auto_retries": case.max_auto_retries,
                "metadata": case.metadata,
                "source_repo": str(source_repo) if source_repo is not None else None,
                "checkout_ref": checkout_ref,
                "expected_candidate_files": list(case.expected_candidate_files),
                "expected_summary_contains": list(case.expected_summary_contains),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
