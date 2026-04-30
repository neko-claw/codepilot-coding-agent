from __future__ import annotations

import json

from codepilot.integrations.deepseek import DeepSeekPlannerClient


class _FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_deepseek_planner_client_retries_transient_timeout(monkeypatch) -> None:
    attempts: list[float] = []
    responses = [TimeoutError("temporary timeout"), _FakeHttpResponse(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "summary": "Recovered plan",
                                "steps": ["Inspect files"],
                                "candidate_commands": ["pytest -q"],
                                "file_reads": [],
                                "file_edits": [],
                            }
                        )
                    }
                }
            ]
        }
    )]

    def fake_urlopen(request, timeout=30.0):
        attempts.append(timeout)
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("codepilot.integrations.deepseek.urlopen", fake_urlopen)
    client = DeepSeekPlannerClient(
        api_key="secret",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )

    response = client.generate_plan(
        task_description="为项目补充测试",
        workdir="/repo",
        capabilities=("read_file", "bash_shell"),
    )

    assert len(attempts) == 2
    assert response.summary == "Recovered plan"
    assert response.steps == ("Inspect files",)


def test_deepseek_planner_client_calls_chat_completions(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=30.0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Plan summary",
                                    "steps": ["Inspect files", "Run tests"],
                                    "candidate_commands": ["pytest -q"],
                                    "file_reads": ["src/app.py"],
                                    "file_edits": [
                                        {
                                            "path": "src/app.py",
                                            "old_string": "return a - b",
                                            "new_string": "return a + b",
                                            "replace_all": False,
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("codepilot.integrations.deepseek.urlopen", fake_urlopen)
    client = DeepSeekPlannerClient(
        api_key="secret",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )

    response = client.generate_plan(
        task_description="为项目补充测试",
        workdir="/repo",
        capabilities=("read_file", "bash_shell"),
        candidate_files=("src/app.py",),
        file_context={"src/app.py": "def add(a, b):\n    return a - b\n"},
        failure_context=[
            {
                "command": "pytest -q",
                "exit_code": 1,
                "stdout": "F",
                "stderr": "assert add(1, 2) == 3",
            }
        ],
        previous_attempts=(
            {
                "summary": "Initial plan",
                "commands": ["pytest -q"],
            },
        ),
    )

    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    body = captured["body"]
    assert body["model"] == "deepseek-chat"
    user_payload = json.loads(body["messages"][1]["content"])
    assert user_payload["candidate_files"] == ["src/app.py"]
    assert user_payload["failure_context"][0]["command"] == "pytest -q"
    assert user_payload["previous_attempts"][0]["summary"] == "Initial plan"
    assert user_payload["workspace_summary"] == ""
    assert "agent scaffold" in body["messages"][0]["content"].lower()
    assert response.summary == "Plan summary"
    assert response.steps == ("Inspect files", "Run tests")
    assert response.candidate_commands == ["pytest -q"]
    assert response.file_reads == ["src/app.py"]
    assert response.file_edits[0].path == "src/app.py"
    assert response.file_edits[0].new_string == "return a + b"


def test_deepseek_planner_client_rejects_invalid_response(monkeypatch) -> None:
    def fake_urlopen(request, timeout=30.0):
        return _FakeHttpResponse({"choices": [{"message": {"content": "not-json"}}]})

    monkeypatch.setattr("codepilot.integrations.deepseek.urlopen", fake_urlopen)
    client = DeepSeekPlannerClient(
        api_key="secret",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )

    try:
        client.generate_plan(
            task_description="修复失败测试",
            workdir="/repo",
            capabilities=("read_file",),
        )
    except ValueError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("expected invalid response to raise ValueError")
