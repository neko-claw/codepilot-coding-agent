"""Dataset adapters for public coding-benchmark exports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .benchmark import BenchmarkCase


@dataclass(frozen=True, slots=True)
class BenchmarkDatasetAdapter:
    """Convert a dataset export into :class:`BenchmarkCase` records."""

    name: str

    def matches(self, path: Path, payload: object) -> bool:
        raise NotImplementedError

    def load(self, path: Path, payload: object) -> list[BenchmarkCase]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class FixtureBenchmarkAdapter(BenchmarkDatasetAdapter):
    """Adapter for the repository's native JSON fixture format."""

    name: str = "fixture"

    def matches(self, path: Path, payload: object) -> bool:
        if isinstance(payload, dict) and "cases" in payload:
            return True
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return "name" in payload[0] and "prompt" in payload[0]
        return False

    def load(self, path: Path, payload: object) -> list[BenchmarkCase]:
        raw_cases = payload["cases"] if isinstance(payload, dict) else payload
        return [_build_case(raw_case) for raw_case in raw_cases]


@dataclass(frozen=True, slots=True)
class HumanEvalAdapter(BenchmarkDatasetAdapter):
    """Adapter for HumanEval-style JSONL or JSON exports."""

    name: str = "humaneval"

    def matches(self, path: Path, payload: object) -> bool:
        records = _as_records(payload)
        if not records:
            return False
        sample = records[0]
        return all(key in sample for key in ("task_id", "prompt", "entry_point"))

    def load(self, path: Path, payload: object) -> list[BenchmarkCase]:
        records = _as_records(payload)
        return [_build_humaneval_case(record) for record in records]


@dataclass(frozen=True, slots=True)
class MBPPAdapter(BenchmarkDatasetAdapter):
    """Adapter for MBPP-style JSONL or JSON exports."""

    name: str = "mbpp"

    def matches(self, path: Path, payload: object) -> bool:
        records = _as_records(payload)
        if not records:
            return False
        sample = records[0]
        return any(key in sample for key in ("test_list", "text", "code")) and "task_id" in sample

    def load(self, path: Path, payload: object) -> list[BenchmarkCase]:
        records = _as_records(payload)
        return [_build_mbpp_case(record) for record in records]


@dataclass(frozen=True, slots=True)
class APPSAdapter(BenchmarkDatasetAdapter):
    """Adapter for APPS-style question/solution exports."""

    name: str = "apps"

    def matches(self, path: Path, payload: object) -> bool:
        records = _as_records(payload)
        if not records:
            return False
        sample = records[0]
        return "question" in sample and any(
            key in sample for key in ("starter_code", "test_list", "public_tests", "solutions")
        )

    def load(self, path: Path, payload: object) -> list[BenchmarkCase]:
        records = _as_records(payload)
        return [
            _build_apps_case(record, index=index)
            for index, record in enumerate(records, start=1)
        ]


@dataclass(frozen=True, slots=True)
class SWEBenchAdapter(BenchmarkDatasetAdapter):
    """Adapter for SWE-bench-style repo-level coding tasks."""

    name: str = "swebench"

    def matches(self, path: Path, payload: object) -> bool:
        records = _as_records(payload)
        if not records:
            return False
        sample = records[0]
        return "instance_id" in sample and "problem_statement" in sample and "repo" in sample

    def load(self, path: Path, payload: object) -> list[BenchmarkCase]:
        records = _as_records(payload)
        return [_build_swebench_case(record) for record in records]


_ADAPTERS: tuple[BenchmarkDatasetAdapter, ...] = (
    HumanEvalAdapter(),
    MBPPAdapter(),
    APPSAdapter(),
    SWEBenchAdapter(),
    FixtureBenchmarkAdapter(),
)


def load_benchmark_cases_from_source(
    path: str | Path, dataset_format: str = "auto"
) -> list[BenchmarkCase]:
    """Load benchmark cases from a fixture or a public coding dataset export."""
    source_path = Path(path)
    payload = _read_payload(source_path)
    if dataset_format != "auto":
        adapter = _adapter_by_name(dataset_format)
        return adapter.load(source_path, payload)
    for adapter in _ADAPTERS:
        if adapter.matches(source_path, payload):
            return adapter.load(source_path, payload)
    raise ValueError(f"Unsupported benchmark dataset format: {source_path}")


def supported_dataset_formats() -> tuple[str, ...]:
    """Return the supported dataset format names."""
    return tuple(adapter.name for adapter in _ADAPTERS)


def _adapter_by_name(name: str) -> BenchmarkDatasetAdapter:
    normalized = name.strip().lower().replace("-", "_")
    for adapter in _ADAPTERS:
        if adapter.name == normalized:
            return adapter
    raise ValueError(f"Unsupported dataset format: {name}")


def _read_payload(path: Path) -> object:
    if path.suffix.lower() == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return json.loads(path.read_text(encoding="utf-8"))


def _as_records(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if "cases" in payload and isinstance(payload["cases"], list):
            return [dict(item) for item in payload["cases"] if isinstance(item, dict)]
        if "records" in payload and isinstance(payload["records"], list):
            return [dict(item) for item in payload["records"] if isinstance(item, dict)]
        return []
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    return []


def _build_case(raw_case: dict[str, Any]) -> BenchmarkCase:
    from .benchmark import BenchmarkCase

    return BenchmarkCase(
        name=str(raw_case["name"]),
        prompt=str(raw_case["prompt"]),
        mode=str(raw_case.get("mode", "auto")),
        seed_files={str(key): str(value) for key, value in raw_case.get("seed_files", {}).items()},
        command_allowlist=_normalize_tuple(raw_case.get("command_allowlist")),
        max_auto_retries=int(raw_case.get("max_auto_retries", 1)),
        expected_candidate_files=_normalize_tuple(raw_case.get("expected_candidate_files")),
        expected_inspected_files=_normalize_tuple(raw_case.get("expected_inspected_files")),
        expected_written_files=_normalize_tuple(raw_case.get("expected_written_files")),
        expected_written_file_contains={
            str(key): str(value)
            for key, value in raw_case.get("expected_written_file_contains", {}).items()
        },
        expected_command_exit_codes={
            str(key): int(value)
            for key, value in raw_case.get("expected_command_exit_codes", {}).items()
        },
        expected_summary_contains=_normalize_tuple(raw_case.get("expected_summary_contains")),
        expected_file_reads=_normalize_tuple(raw_case.get("expected_file_reads")),
        metadata={str(key): str(value) for key, value in raw_case.get("metadata", {}).items()},
    )


def _build_humaneval_case(record: dict[str, Any]) -> BenchmarkCase:
    from .benchmark import BenchmarkCase

    entry_point = str(record["entry_point"])
    prompt = str(record["prompt"])
    test_source = str(record.get("test", ""))
    source_path = f"src/{entry_point}.py"
    test_path = f"tests/test_{entry_point}.py"
    seed_files = dict(record.get("seed_files", {})) or {
        source_path: _build_python_stub(entry_point, prompt),
        test_path: _build_python_test_file(entry_point, test_source),
        "src/__init__.py": f"from .{entry_point} import {entry_point}\n",
    }
    return BenchmarkCase(
        name=str(record.get("task_id", entry_point)),
        prompt=_compose_prompt(prompt, entry_point, dataset_name="HumanEval"),
        mode=str(record.get("mode", "auto")),
        seed_files={str(key): str(value) for key, value in seed_files.items()},
        command_allowlist=_normalize_tuple(record.get("command_allowlist")) or ("pytest -q",),
        max_auto_retries=int(record.get("max_auto_retries", 1)),
        expected_candidate_files=_normalize_tuple(record.get("expected_candidate_files"))
        or (source_path, test_path),
        expected_inspected_files=_normalize_tuple(record.get("expected_inspected_files")),
        expected_written_files=_normalize_tuple(record.get("expected_written_files"))
        or (source_path, test_path),
        expected_written_file_contains={
            str(key): str(value)
            for key, value in record.get("expected_written_file_contains", {}).items()
        },
        expected_command_exit_codes={
            str(key): int(value)
            for key, value in record.get("expected_command_exit_codes", {}).items()
        },
        expected_summary_contains=_normalize_tuple(record.get("expected_summary_contains")),
        expected_file_reads=_normalize_tuple(record.get("expected_file_reads"))
        or (source_path, test_path),
        metadata={
            "dataset": "humaneval",
            "entry_point": entry_point,
            "task_id": str(record.get("task_id", entry_point)),
        },
    )


def _build_mbpp_case(record: dict[str, Any]) -> BenchmarkCase:
    from .benchmark import BenchmarkCase

    entry_point = str(record.get("entry_point") or record.get("task_id"))
    prompt = str(record.get("text") or record.get("prompt") or record.get("task"))
    test_list = record.get("test_list", [])
    if isinstance(test_list, list):
        test_source = "\n".join(f"    {line}" for line in test_list)
    else:
        test_source = str(test_list)
    source_path = f"src/{entry_point}.py"
    test_path = f"tests/test_{entry_point}.py"
    seed_files = dict(record.get("seed_files", {})) or {
        source_path: _build_python_stub(entry_point, prompt),
        test_path: _build_mbpp_test_file(entry_point, test_source),
        "src/__init__.py": f"from .{entry_point} import {entry_point}\n",
    }
    return BenchmarkCase(
        name=str(record.get("task_id", entry_point)),
        prompt=_compose_prompt(prompt, entry_point, dataset_name="MBPP"),
        mode=str(record.get("mode", "auto")),
        seed_files={str(key): str(value) for key, value in seed_files.items()},
        command_allowlist=_normalize_tuple(record.get("command_allowlist")) or ("pytest -q",),
        max_auto_retries=int(record.get("max_auto_retries", 1)),
        expected_candidate_files=_normalize_tuple(record.get("expected_candidate_files"))
        or (source_path, test_path),
        expected_inspected_files=_normalize_tuple(record.get("expected_inspected_files")),
        expected_written_files=_normalize_tuple(record.get("expected_written_files"))
        or (source_path, test_path),
        expected_written_file_contains={
            str(key): str(value)
            for key, value in record.get("expected_written_file_contains", {}).items()
        },
        expected_command_exit_codes={
            str(key): int(value)
            for key, value in record.get("expected_command_exit_codes", {}).items()
        },
        expected_summary_contains=_normalize_tuple(record.get("expected_summary_contains")),
        expected_file_reads=_normalize_tuple(record.get("expected_file_reads"))
        or (source_path, test_path),
        metadata={
            "dataset": "mbpp",
            "entry_point": entry_point,
            "task_id": str(record.get("task_id", entry_point)),
        },
    )


def _build_swebench_case(record: dict[str, Any]) -> BenchmarkCase:
    from .benchmark import BenchmarkCase

    instance_id = str(record["instance_id"])
    problem_statement = str(record["problem_statement"])
    repo = str(record["repo"])
    base_commit = str(record.get("base_commit", ""))
    prompt = (
        f"{problem_statement.strip()}\n\n"
        f"Repo: {repo}\n"
        f"Base commit: {base_commit or 'unknown'}\n\n"
        "这是一个仓库级修复任务。请先阅读关键文件，理解现有结构，再实施最小修复并验证。\n"
    )
    seed_files = {str(key): str(value) for key, value in record.get("seed_files", {}).items()}
    expected_candidate_files = _normalize_tuple(record.get("expected_candidate_files"))
    expected_file_reads = _normalize_tuple(record.get("expected_file_reads"))
    if not expected_candidate_files:
        expected_candidate_files = expected_file_reads or tuple(seed_files.keys())
    if not expected_file_reads:
        expected_file_reads = expected_candidate_files or tuple(seed_files.keys())
    return BenchmarkCase(
        name=instance_id,
        prompt=prompt,
        mode=str(record.get("mode", "auto")),
        seed_files=seed_files,
        command_allowlist=_normalize_tuple(record.get("command_allowlist")) or ("pytest -q",),
        max_auto_retries=int(record.get("max_auto_retries", 1)),
        expected_candidate_files=expected_candidate_files,
        expected_inspected_files=_normalize_tuple(record.get("expected_inspected_files")),
        expected_written_files=_normalize_tuple(record.get("expected_written_files")),
        expected_written_file_contains={
            str(key): str(value)
            for key, value in record.get("expected_written_file_contains", {}).items()
        },
        expected_command_exit_codes={
            str(key): int(value)
            for key, value in record.get("expected_command_exit_codes", {}).items()
        },
        expected_summary_contains=_normalize_tuple(record.get("expected_summary_contains"))
        or (problem_statement[:40], repo),
        expected_file_reads=expected_file_reads,
        metadata={
            "dataset": "swebench",
            "instance_id": instance_id,
            "repo": repo,
            "base_commit": base_commit,
        },
    )


def _build_apps_case(record: dict[str, Any], *, index: int) -> BenchmarkCase:
    from .benchmark import BenchmarkCase

    task_id = str(record.get("problem_id") or record.get("task_id") or f"apps-{index}")
    prompt = str(record.get("question") or record.get("prompt") or record.get("problem"))
    entry_point = str(record.get("entry_point") or record.get("function_name") or "solve")
    starter_code = str(record.get("starter_code") or "").strip()
    source_path = f"src/{entry_point}.py"
    test_path = f"tests/test_{entry_point}.py"
    if starter_code:
        seed_files = dict(record.get("seed_files", {})) or {
            source_path: starter_code + ("\n" if not starter_code.endswith("\n") else ""),
            test_path: _build_apps_test_file(entry_point, record),
            "src/__init__.py": f"from .{entry_point} import {entry_point}\n",
        }
    else:
        seed_files = dict(record.get("seed_files", {})) or {
            source_path: _build_python_stub(entry_point, prompt),
            test_path: _build_apps_test_file(entry_point, record),
            "src/__init__.py": f"from .{entry_point} import {entry_point}\n",
        }
    return BenchmarkCase(
        name=task_id,
        prompt=_compose_prompt(prompt, entry_point, dataset_name="APPS"),
        mode=str(record.get("mode", "auto")),
        seed_files={str(key): str(value) for key, value in seed_files.items()},
        command_allowlist=_normalize_tuple(record.get("command_allowlist")) or ("pytest -q",),
        max_auto_retries=int(record.get("max_auto_retries", 1)),
        expected_candidate_files=_normalize_tuple(record.get("expected_candidate_files"))
        or (source_path, test_path),
        expected_inspected_files=_normalize_tuple(record.get("expected_inspected_files")),
        expected_written_files=_normalize_tuple(record.get("expected_written_files"))
        or (source_path, test_path),
        expected_written_file_contains={
            str(key): str(value)
            for key, value in record.get("expected_written_file_contains", {}).items()
        },
        expected_command_exit_codes={
            str(key): int(value)
            for key, value in record.get("expected_command_exit_codes", {}).items()
        },
        expected_summary_contains=_normalize_tuple(record.get("expected_summary_contains"))
        or (prompt[:40], entry_point),
        expected_file_reads=_normalize_tuple(record.get("expected_file_reads"))
        or (source_path, test_path),
        metadata={
            "dataset": "apps",
            "task_id": task_id,
            "entry_point": entry_point,
        },
    )


def _build_apps_test_file(entry_point: str, record: dict[str, Any]) -> str:
    test_list = record.get("test_list", [])
    if isinstance(test_list, list) and test_list:
        test_body = "\n".join(f"    {line}" for line in test_list)
        return (
            "import sys\n"
            "from pathlib import Path\n\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
            f"from src.{entry_point} import {entry_point}\n\n\n"
            f"def test_{entry_point}_apps():\n"
            f"{test_body}\n"
        )
    public_tests = record.get("public_tests")
    if isinstance(public_tests, str) and public_tests.strip():
        return public_tests if public_tests.endswith("\n") else public_tests + "\n"
    return (
        "import sys\n"
        "from pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        f"from src.{entry_point} import {entry_point}\n\n\n"
        f"def test_{entry_point}_apps():\n"
        f"    assert {entry_point} is not None\n"
    )


def _compose_prompt(prompt: str, entry_point: str, *, dataset_name: str) -> str:
    return (
        f"{prompt.strip()}\n\n"
        f"你正在执行 {dataset_name} 数据集任务。请优先完成对应实现、补全测试，并确保 "
        f"`pytest -q` 通过。\n"
        f"目标入口: {entry_point}\n"
    )


def _build_python_stub(entry_point: str, prompt: str) -> str:
    signature = _extract_signature(prompt, entry_point)
    return (
        f"{signature}\n"
        f'    """TODO: implement {entry_point}."""\n'
        f'    raise NotImplementedError("Implement {entry_point}")\n'
    )


def _build_python_test_file(entry_point: str, test_source: str) -> str:
    if not test_source.strip():
        test_source = f"assert {entry_point} is not None"
    return (
        "import sys\n"
        "from pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        f"from src.{entry_point} import {entry_point}\n\n\n"
        f"{test_source.rstrip()}\n"
    )


def _build_mbpp_test_file(entry_point: str, test_source: str) -> str:
    if not test_source.strip():
        test_source = f"assert {entry_point} is not None"
    return (
        "import sys\n"
        "from pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        f"from src.{entry_point} import {entry_point}\n\n\n"
        f"def test_{entry_point}_dataset():\n"
        f"{test_source.rstrip()}\n"
    )


def _extract_signature(prompt: str, entry_point: str) -> str:
    pattern = re.compile(rf"^\s*def\s+{re.escape(entry_point)}\s*\(.*\):\s*$", re.MULTILINE)
    match = pattern.search(prompt)
    if match is not None:
        return match.group(0).strip()
    fallback = re.search(r"^\s*def\s+[A-Za-z_][A-Za-z0-9_]*\s*\(.*\):\s*$", prompt, re.MULTILINE)
    if fallback is not None:
        return fallback.group(0).strip()
    return f"def {entry_point}(*args, **kwargs):"


def _normalize_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        return (value,)
    return (str(value),)
