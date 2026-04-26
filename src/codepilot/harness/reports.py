"""Serialization and formatting helpers for CodePilot harness runs."""

from __future__ import annotations

import json
from typing import Any

from codepilot.eval import BenchmarkSuiteResult, SWEBenchSuiteRunResult
from codepilot.runtime.session import TaskSessionResult
from codepilot.harness.runner import HarnessLoopResult


def serialize_session_result(result: TaskSessionResult) -> dict[str, Any]:
    """Convert a session result into a JSON-friendly dictionary."""
    return {
        "session_id": result.session_id,
        "request": {
            "description": result.request.description,
            "workdir": result.request.workdir,
            "mode": result.request.mode,
        },
        "plan": {
            "status": result.plan.status,
            "can_execute": result.plan.can_execute,
            "next_action": result.plan.next_action,
            "summary": result.plan.summary,
            "steps": list(result.plan.steps),
            "candidate_files": list(result.plan.candidate_files),
            "candidate_commands": list(result.plan.candidate_commands),
            "risk": {
                "level": result.plan.risk.level,
                "requires_confirmation": result.plan.risk.requires_confirmation,
                "reason": result.plan.risk.reason,
            },
            "user_options": list(result.plan.user_options),
        },
        "local_files": list(result.local_files),
        "inspected_files": list(result.inspected_files),
        "github_snapshot": _serialize_optional_dataclass(result.github_snapshot),
        "edit_results": [
            {
                "path": item.path,
                "diff": list(item.diff),
                "syntax_check": item.syntax_check,
                "applied": item.applied,
                "reverted": item.reverted,
            }
            for item in result.edit_results
        ],
        "command_results": [
            {
                "command": item.command,
                "exit_code": item.exit_code,
                "stdout": item.stdout,
                "stderr": item.stderr,
            }
            for item in result.command_results
        ],
        "planner_trace": [
            {
                "attempt_index": item.attempt_index,
                "source": item.source,
                "summary": item.summary,
                "note": item.note,
            }
            for item in result.planner_trace
        ],
        "retry_trace": [
            {
                "attempt_index": item.attempt_index,
                "failure_type": item.failure_type,
                "summary": item.summary,
                "commands": list(item.commands),
                "retried": item.retried,
                "reason": item.reason,
            }
            for item in result.retry_trace
        ],
        "failure_hints": list(result.failure_hints),
        "rollback_snapshot_id": result.rollback_snapshot_id,
    }


def serialize_suite_result(result: BenchmarkSuiteResult | SWEBenchSuiteRunResult) -> dict[str, Any]:
    """Convert a benchmark suite result into a JSON-friendly dictionary."""
    benchmark_result = getattr(result, "benchmark_result", result)
    payload: dict[str, Any] = {
        "total": benchmark_result.total,
        "passed": benchmark_result.passed,
        "failed": benchmark_result.failed,
        "cases": [
            {
                "name": case_result.case.name,
                "passed": case_result.passed,
                "observations": list(case_result.observations),
                "failures": list(case_result.failures),
                "case": _serialize_benchmark_case(case_result.case),
            }
            for case_result in benchmark_result.case_results
        ],
    }
    if isinstance(result, SWEBenchSuiteRunResult):
        payload["runs"] = [
            {
                "case": run_result.case.name,
                "workspace_path": str(run_result.workspace_path),
                "session_result": _serialize_optional_dataclass(run_result.session_result),
            }
            for run_result in result.run_results
        ]
    return payload


def format_harness_text(result: TaskSessionResult) -> str:
    """Render a compact human-readable harness report."""
    payload = serialize_session_result(result)
    plan = payload["plan"]
    candidate_files = [f"- {path}" for path in plan["candidate_files"]] or ["- none"]
    inspected_files = [f"- {path}" for path in payload["inspected_files"]] or ["- none"]
    candidate_commands = [f"- {command}" for command in plan["candidate_commands"]] or ["- none"]
    edit_results = [_format_edit_result_text(item) for item in payload["edit_results"]] or [
        "- none"
    ]
    command_results = [
        f"- {item['command']} => {item['exit_code']}" for item in payload["command_results"]
    ] or ["- none"]
    lines = [
        "CodePilot Harness Report",
        f"session_id: {payload['session_id']}",
        f"workspace: {payload['request']['workdir']}",
        f"mode: {payload['request']['mode']}",
        f"status: {plan['status']}",
        f"next_action: {plan['next_action']}",
        f"summary: {plan['summary']}",
        f"risk: {plan['risk']['level']} ({plan['risk']['reason']})",
        "candidate_files:",
        *candidate_files,
        "inspected_files:",
        *inspected_files,
        "candidate_commands:",
        *candidate_commands,
        "edit_results:",
        *edit_results,
        "command_results:",
        *command_results,
    ]
    if payload["failure_hints"]:
        lines.extend(["failure_hints:", *[f"- {hint}" for hint in payload["failure_hints"]]])
    if payload["rollback_snapshot_id"]:
        lines.append(f"rollback_snapshot: {payload['rollback_snapshot_id']}")
    return "\n".join(lines)


def format_harness_markdown(result: TaskSessionResult) -> str:
    """Render a markdown report for a harness session."""
    payload = serialize_session_result(result)
    plan = payload["plan"]
    sections = [
        "# CodePilot Harness Report",
        "",
        f"- Session ID: `{payload['session_id']}`",
        f"- Workspace: `{payload['request']['workdir']}`",
        f"- Mode: `{payload['request']['mode']}`",
        f"- Status: `{plan['status']}`",
        f"- Next action: `{plan['next_action']}`",
        f"- Risk: `{plan['risk']['level']}` — {plan['risk']['reason']}",
        "",
        "## Summary",
        plan["summary"],
        "",
        "## Candidate Files",
        *(_list_or_none([f"`{path}`" for path in plan["candidate_files"]])),
        "",
        "## Inspected Files",
        *(_list_or_none([f"`{path}`" for path in payload["inspected_files"]])),
        "",
        "## Candidate Commands",
        *(_list_or_none([f"`{command}`" for command in plan["candidate_commands"]])),
        "",
        "## Edit Results",
        *(_list_or_none([_format_edit_result_markdown(item) for item in payload["edit_results"]])),
        "",
        "## Command Results",
        *(
            _list_or_none(
                [
                    f"`{item['command']}` => `{item['exit_code']}`"
                    for item in payload["command_results"]
                ]
            )
        ),
    ]
    if payload["failure_hints"]:
        sections.extend(
            ["", "## Failure Hints", *[f"- {hint}" for hint in payload["failure_hints"]]]
        )
    if payload["rollback_snapshot_id"]:
        sections.extend(["", f"- Rollback snapshot: `{payload['rollback_snapshot_id']}`"])
    return "\n".join(sections)


def format_harness_json(result: TaskSessionResult) -> str:
    """Render a JSON report for a harness session."""
    return json.dumps(serialize_session_result(result), ensure_ascii=False, indent=2)


def format_suite_text(result: BenchmarkSuiteResult | SWEBenchSuiteRunResult) -> str:
    """Render a compact human-readable benchmark suite report."""
    payload = serialize_suite_result(result)
    lines = [
        "CodePilot Harness Benchmark Report",
        f"total: {payload['total']}",
        f"passed: {payload['passed']}",
        f"failed: {payload['failed']}",
    ]
    for case_result in payload["cases"]:
        failure_text = "; ".join(case_result["failures"]) if case_result["failures"] else "none"
        lines.append(
            f"- {case_result['name']} passed={case_result['passed']} failures={failure_text}"
        )
    return "\n".join(lines)


def format_suite_markdown(result: BenchmarkSuiteResult | SWEBenchSuiteRunResult) -> str:
    """Render a markdown benchmark-suite report."""
    payload = serialize_suite_result(result)
    sections = [
        "# CodePilot Harness Benchmark Report",
        "",
        f"- Total: `{payload['total']}`",
        f"- Passed: `{payload['passed']}`",
        f"- Failed: `{payload['failed']}`",
        "",
        "## Cases",
    ]
    for case_result in payload["cases"]:
        sections.append(f"- `{case_result['name']}` passed={case_result['passed']}")
        if case_result["failures"]:
            sections.extend(f"  - failure: {failure}" for failure in case_result["failures"])
    return "\n".join(sections)


def format_suite_json(result: BenchmarkSuiteResult | SWEBenchSuiteRunResult) -> str:
    """Render a JSON benchmark-suite report."""
    return json.dumps(serialize_suite_result(result), ensure_ascii=False, indent=2)


def serialize_loop_result(result: HarnessLoopResult) -> dict[str, Any]:
    """Convert a closed-loop harness run into a JSON-friendly dictionary."""
    return {
        "description": result.description,
        "workdir": result.workdir,
        "completed": result.completed,
        "stop_reason": result.stop_reason,
        "rounds": [
            {
                "round_index": round_result.round_index,
                "success": round_result.success,
                "reason": round_result.reason,
                "session_result": serialize_session_result(round_result.session_result),
            }
            for round_result in result.rounds
        ],
    }


def format_loop_text(result: HarnessLoopResult) -> str:
    """Render a compact human-readable report for a looped harness run."""
    payload = serialize_loop_result(result)
    lines = [
        "CodePilot Harness Loop Report",
        f"description: {payload['description']}",
        f"workdir: {payload['workdir']}",
        f"completed: {payload['completed']}",
        f"stop_reason: {payload['stop_reason']}",
    ]
    for round_result in payload["rounds"]:
        lines.append(
            f"- round {round_result['round_index']} success={round_result['success']} "
            f"reason={round_result['reason']}"
        )
    return "\n".join(lines)


def format_loop_markdown(result: HarnessLoopResult) -> str:
    """Render a markdown report for a looped harness run."""
    payload = serialize_loop_result(result)
    sections = [
        "# CodePilot Harness Loop Report",
        "",
        f"- Description: `{payload['description']}`",
        f"- Workdir: `{payload['workdir']}`",
        f"- Completed: `{payload['completed']}`",
        f"- Stop reason: `{payload['stop_reason']}`",
        "",
        "## Rounds",
    ]
    for round_result in payload["rounds"]:
        sections.append(
            f"- Round `{round_result['round_index']}` success=`{round_result['success']}` "
            f"reason={round_result['reason']}"
        )
    return "\n".join(sections)


def format_loop_json(result: HarnessLoopResult) -> str:
    """Render a JSON report for a looped harness run."""
    return json.dumps(serialize_loop_result(result), ensure_ascii=False, indent=2)


def _format_edit_result_text(item: dict[str, Any]) -> str:
    return (
        f"- {item['path']} applied={item['applied']} "
        f"reverted={item['reverted']} syntax={item['syntax_check']}"
    )


def _format_edit_result_markdown(item: dict[str, Any]) -> str:
    return (
        f"- `{item['path']}` applied={item['applied']} "
        f"reverted={item['reverted']} syntax={item['syntax_check']}"
    )


def _list_or_none(items: list[str]) -> list[str]:
    return items or ["- none"]


def _serialize_optional_dataclass(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "_asdict"):
        return value._asdict()  # pragma: no cover - compatibility fallback
    if hasattr(value, "__dict__"):
        return {key: _serialize_optional_dataclass(item) for key, item in value.__dict__.items()}
    return value


def _serialize_benchmark_case(case: Any) -> dict[str, Any]:
    return {
        "name": case.name,
        "prompt": case.prompt,
        "mode": case.mode,
        "seed_files": dict(case.seed_files),
        "command_allowlist": list(case.command_allowlist or ()),
        "max_auto_retries": case.max_auto_retries,
        "expected_candidate_files": list(case.expected_candidate_files),
        "expected_inspected_files": list(case.expected_inspected_files),
        "expected_written_files": list(case.expected_written_files),
        "expected_written_file_contains": dict(case.expected_written_file_contains),
        "expected_command_exit_codes": dict(case.expected_command_exit_codes),
        "expected_summary_contains": list(case.expected_summary_contains),
        "expected_file_reads": list(case.expected_file_reads),
        "metadata": dict(case.metadata),
    }
