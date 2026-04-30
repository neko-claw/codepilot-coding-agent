"""GitHub API integration helpers."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

GITHUB_API_BASE_URL = "https://api.github.com"


@dataclass(frozen=True, slots=True)
class GitHubRepoRef:
    """Normalized GitHub repository reference."""

    owner: str
    name: str


@dataclass(frozen=True, slots=True)
class GitHubRepoSnapshot:  # pylint: disable=too-many-instance-attributes
    """Minimal public repository snapshot fetched from GitHub."""

    full_name: str
    description: str
    default_branch: str
    star_count: int
    file_count: int
    sample_paths: list[str]
    readme_excerpt: str
    html_url: str


class GitHubRepoClient:
    """Tiny GitHub REST client for public repository context."""

    def __init__(
        self,
        *,
        base_url: str = GITHUB_API_BASE_URL,
        token: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def fetch_snapshot(self, repo_ref: GitHubRepoRef) -> GitHubRepoSnapshot:
        """Fetch repository metadata, tree, and README excerpt."""
        repo_payload = self._get_json(f"/repos/{repo_ref.owner}/{repo_ref.name}")
        default_branch = str(repo_payload["default_branch"])
        tree_payload = self._get_json(
            f"/repos/{repo_ref.owner}/{repo_ref.name}/git/trees/{default_branch}?recursive=1"
        )
        readme_payload = self._get_json(f"/repos/{repo_ref.owner}/{repo_ref.name}/readme")
        tree_items = [
            item["path"] for item in tree_payload.get("tree", []) if item.get("type") == "blob"
        ]
        readme_excerpt = _decode_readme_excerpt(readme_payload)
        html_url = str(
            repo_payload.get("html_url") or f"https://github.com/{repo_ref.owner}/{repo_ref.name}"
        )
        return GitHubRepoSnapshot(
            full_name=str(repo_payload["full_name"]),
            description=str(repo_payload.get("description") or ""),
            default_branch=default_branch,
            star_count=int(repo_payload.get("stargazers_count") or 0),
            file_count=len(tree_items),
            sample_paths=sorted(tree_items)[:10],
            readme_excerpt=readme_excerpt,
            html_url=html_url,
        )

    def _get_json(self, path: str) -> dict[str, object]:
        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "CodePilot/0.1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, headers=headers)
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))


def parse_github_remote(remote_url: str) -> GitHubRepoRef:
    """Extract owner and repo name from a GitHub remote URL."""
    cleaned = remote_url.strip()
    if cleaned.startswith("git@github.com:"):
        path = cleaned.split(":", maxsplit=1)[1]
    elif cleaned.startswith("https://github.com/"):
        parsed = urlparse(cleaned)
        path = parsed.path.lstrip("/")
    else:
        raise ValueError("unsupported GitHub remote URL")

    normalized = path.removesuffix(".git")
    owner, name = normalized.split("/", maxsplit=1)
    return GitHubRepoRef(owner=owner, name=name)


def infer_github_repo_from_local(workdir: str | Path) -> GitHubRepoRef | None:
    """Inspect .git/config and infer the origin GitHub repository if possible."""
    config_path = Path(workdir) / ".git" / "config"
    if not config_path.exists():
        return None

    in_origin = False
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("[remote "):
            in_origin = line == '[remote "origin"]'
            continue
        if in_origin and line.startswith("url = "):
            try:
                return parse_github_remote(line.split("=", maxsplit=1)[1].strip())
            except ValueError:
                return None
    return None


def _decode_readme_excerpt(readme_payload: dict[str, object], max_chars: int = 400) -> str:
    content = str(readme_payload.get("content") or "")
    encoding = str(readme_payload.get("encoding") or "")
    if encoding == "base64" and content:
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
    else:
        decoded = content
    excerpt = decoded.strip()
    return excerpt[:max_chars]
