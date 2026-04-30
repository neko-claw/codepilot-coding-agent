"""DeepSeek planner integration."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class FileEditSuggestion:
    """Deterministic file replacement suggested by the planner."""

    path: str
    old_string: str
    new_string: str
    replace_all: bool = False


@dataclass(frozen=True, slots=True)
class FileWriteSuggestion:
    """Full-file write suggested by the planner."""

    path: str
    content: str


@dataclass(frozen=True, slots=True)
class PlannerSuggestion:
    """Structured planner output from DeepSeek."""

    summary: str
    steps: tuple[str, ...]
    candidate_commands: list[str]
    file_reads: list[str]
    file_edits: list[FileEditSuggestion]
    file_writes: list[FileWriteSuggestion] = field(default_factory=list)


class DeepSeekPlannerClient:
    """OpenAI-compatible DeepSeek client for planning output."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 30.0,
        retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = max(0, retries)

    def generate_plan(  # pylint: disable=too-many-arguments
        self,
        *,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
        candidate_files: tuple[str, ...] = (),
        file_context: dict[str, str] | None = None,
        failure_context: list[dict[str, object]] | None = None,
        previous_attempts: tuple[dict[str, object], ...] = (),
        workspace_summary: str = "",
    ) -> PlannerSuggestion:
        """Request a planning suggestion from DeepSeek."""
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a coding agent planner. Return strict JSON with keys "
                        "summary (string), steps (array of strings), "
                        "candidate_commands (array of strings), "
                        "file_reads (array of strings), "
                        "file_edits (array of objects with path, old_string, "
                        "new_string, replace_all), "
                        "file_writes (array of objects with path, content). "
                        "Use file_edits for deterministic replacements in existing files. "
                        "Use file_writes when you need to create a new file or fully rewrite "
                        "a small file from scratch. For prompts about creating a new agent from "
                        "scratch, prefer an agent scaffold with a runnable CLI entrypoint, a "
                        "small agent core module, tests, and README before adding extra features. "
                        "For existing repositories, read README, pyproject, docs, and tests first, "
                        "then summarize the repository structure before editing. "
                        "When failure_context is present, use it to adjust the next repair "
                        "attempt instead of repeating the same edit or command sequence."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task_description": task_description,
                            "workdir": workdir,
                            "capabilities": capabilities,
                            "candidate_files": candidate_files,
                            "file_context": file_context or {},
                            "failure_context": failure_context or [],
                            "previous_attempts": list(previous_attempts),
                            "workspace_summary": workspace_summary,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                request = Request(
                    f"{self.base_url}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    data = json.loads(response.read().decode("utf-8"))
                return self._parse_response(data)
            except (OSError, TimeoutError, ValueError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
        if last_error is None:  # pragma: no cover - defensive guard
            raise RuntimeError("DeepSeek planner failed without an error")
        raise last_error

    def _parse_response(self, payload: dict[str, object]) -> PlannerSuggestion:
        try:
            raw_content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(raw_content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("DeepSeek response did not contain valid JSON plan data") from exc
        summary = str(parsed["summary"])
        steps = tuple(str(item) for item in parsed["steps"])
        commands = [str(item) for item in parsed.get("candidate_commands", [])]
        file_reads = [str(item) for item in parsed.get("file_reads", [])]
        file_edits = [self._parse_file_edit(item) for item in parsed.get("file_edits", [])]
        file_writes = [self._parse_file_write(item) for item in parsed.get("file_writes", [])]
        return PlannerSuggestion(
            summary=summary,
            steps=steps,
            candidate_commands=commands,
            file_reads=file_reads,
            file_edits=file_edits,
            file_writes=file_writes,
        )

    @staticmethod
    def _parse_file_edit(payload: object) -> FileEditSuggestion:
        if not isinstance(payload, dict):
            raise ValueError("DeepSeek file_edits items must be JSON objects")
        return FileEditSuggestion(
            path=str(payload["path"]),
            old_string=str(payload["old_string"]),
            new_string=str(payload["new_string"]),
            replace_all=bool(payload.get("replace_all", False)),
        )

    @staticmethod
    def _parse_file_write(payload: object) -> FileWriteSuggestion:
        if not isinstance(payload, dict):
            raise ValueError("DeepSeek file_writes items must be JSON objects")
        return FileWriteSuggestion(
            path=str(payload["path"]),
            content=str(payload["content"]),
        )
