"""Harness execution helpers for developer-day workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codepilot.eval import (
    BenchmarkSuiteResult,
    SWEBenchSuiteRunResult,
    load_benchmark_cases,
    run_benchmark_suite,
    run_swebench_suite,
)
from codepilot.runtime.session import TaskSessionResult, run_task_session
from codepilot.storage.session_store import SessionStore


def run_harness_session(
    *,
    description: str,
    workdir: str | Path,
    mode: str = "auto",
    planner_client: Any | None = None,
    command_allowlist: tuple[str, ...] | None = None,
    strict_command_allowlist: bool = False,
    storage_dir: str | Path | None = None,
    max_auto_retries: int = 1,
) -> TaskSessionResult:
    """Run one developer harness session and return the underlying runtime result."""
    return run_task_session(
        description=description,
        workdir=workdir,
        mode=mode,
        planner_client=planner_client,
        command_allowlist=command_allowlist,
        strict_command_allowlist=strict_command_allowlist,
        storage_dir=storage_dir,
        max_auto_retries=max_auto_retries,
    )


def run_harness_suite(
    suite_path: str | Path,
    *,
    planner_client: Any,
    dataset_format: str = "auto",
    source_repo: str | Path | None = None,
    checkout_ref: str | None = None,
) -> BenchmarkSuiteResult | SWEBenchSuiteRunResult:
    """Run a benchmark suite through the harness pipeline."""
    cases = load_benchmark_cases(suite_path, dataset_format=dataset_format)
    if dataset_format == "swebench":
        return run_swebench_suite(
            cases,
            planner_client,
            source_repo=source_repo,
            checkout_ref=checkout_ref,
        )
    return run_benchmark_suite(cases, planner_client)



def resume_harness_session(
    session_id: str,
    *,
    storage_dir: str | Path,
    planner_client: Any | None,
    mode: str | None = None,
    max_auto_retries: int = 1,
    strict_command_allowlist: bool = False,
) -> TaskSessionResult:
    """Resume a previously recorded harness session using saved history metadata."""
    store = SessionStore(storage_dir)
    record = store.get_session(session_id)
    if record is None:
        raise FileNotFoundError(f"session not found: {session_id}")
    return run_harness_session(
        description=record.description,
        workdir=record.workdir,
        mode=mode or record.mode,
        planner_client=planner_client,
        command_allowlist=tuple(record.commands) or None,
        strict_command_allowlist=strict_command_allowlist,
        storage_dir=storage_dir,
        max_auto_retries=max_auto_retries,
    )
