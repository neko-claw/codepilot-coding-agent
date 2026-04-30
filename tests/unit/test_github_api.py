from __future__ import annotations

import json
from pathlib import Path

from codepilot.integrations.github import (
    GitHubRepoClient,
    GitHubRepoRef,
    infer_github_repo_from_local,
    parse_github_remote,
)


class _FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_parse_github_remote_supports_https_and_ssh() -> None:
    assert parse_github_remote("https://github.com/octo/demo.git") == GitHubRepoRef(
        owner="octo",
        name="demo",
    )
    assert parse_github_remote("git@github.com:octo/demo.git") == GitHubRepoRef(
        owner="octo",
        name="demo",
    )


def test_fetch_snapshot_collects_metadata_tree_and_readme(monkeypatch) -> None:
    payloads = {
        "https://api.github.com/repos/octo/demo": {
            "full_name": "octo/demo",
            "description": "demo repo",
            "default_branch": "main",
            "stargazers_count": 7,
        },
        "https://api.github.com/repos/octo/demo/git/trees/main?recursive=1": {
            "tree": [
                {"path": "README.md", "type": "blob"},
                {"path": "src/app.py", "type": "blob"},
                {"path": "tests/test_app.py", "type": "blob"},
            ]
        },
        "https://api.github.com/repos/octo/demo/readme": {
            "content": "IyBEZW1vIFJlcG8KClNhbXBsZSByZWFkbWUu",
            "encoding": "base64",
        },
    }

    def fake_urlopen(request, timeout=10.0):
        return _FakeHttpResponse(payloads[request.full_url])

    monkeypatch.setattr("codepilot.integrations.github.urlopen", fake_urlopen)
    client = GitHubRepoClient()

    snapshot = client.fetch_snapshot(GitHubRepoRef(owner="octo", name="demo"))

    assert snapshot.full_name == "octo/demo"
    assert snapshot.default_branch == "main"
    assert snapshot.star_count == 7
    assert snapshot.file_count == 3
    assert snapshot.sample_paths == ["README.md", "src/app.py", "tests/test_app.py"]
    assert "Demo Repo" in snapshot.readme_excerpt


def test_infer_github_repo_from_local_origin(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    git_dir = project / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:octo/demo.git\n',
        encoding="utf-8",
    )

    assert infer_github_repo_from_local(project) == GitHubRepoRef(owner="octo", name="demo")
