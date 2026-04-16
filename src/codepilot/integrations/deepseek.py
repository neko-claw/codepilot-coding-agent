"""DeepSeek planner integration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class PlannerSuggestion:
    """Structured planner output from DeepSeek."""

    summary: str
    steps: tuple[str, ...]
    candidate_commands: list[str]


class DeepSeekPlannerClient:
    """OpenAI-compatible DeepSeek client for planning output."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate_plan(
        self,
        *,
        task_description: str,
        workdir: str,
        capabilities: tuple[str, ...],
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
                        "candidate_commands (array of strings)."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task_description": task_description,
                            "workdir": workdir,
                            "capabilities": capabilities,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
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

    def _parse_response(self, payload: dict[str, object]) -> PlannerSuggestion:
        try:
            raw_content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(raw_content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("DeepSeek response did not contain valid JSON plan data") from exc
        summary = str(parsed["summary"])
        steps = tuple(str(item) for item in parsed["steps"])
        commands = [str(item) for item in parsed.get("candidate_commands", [])]
        return PlannerSuggestion(summary=summary, steps=steps, candidate_commands=commands)
