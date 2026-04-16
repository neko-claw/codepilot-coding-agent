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
    )

    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    body = captured["body"]
    assert body["model"] == "deepseek-chat"
    assert response.summary == "Plan summary"
    assert response.steps == ("Inspect files", "Run tests")
    assert response.candidate_commands == ["pytest -q"]


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
