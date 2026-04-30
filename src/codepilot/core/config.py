"""Project configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_DEEPSEEK_TIMEOUT = 15.0
DEFAULT_DEEPSEEK_RETRIES = 2
DEFAULT_STORAGE_DIRNAME = ".codepilot"


@dataclass(frozen=True, slots=True)
class CodePilotConfig:
    """Resolved project-level configuration."""

    project_root: Path
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout: float
    deepseek_retries: int
    storage_dir: Path

    @property
    def deepseek_enabled(self) -> bool:
        """Whether the DeepSeek planner is available."""
        return bool(self.deepseek_api_key)


def load_config(project_root: str | Path) -> CodePilotConfig:
    """Load project configuration from .env plus process environment."""
    root = Path(project_root).resolve()
    env_values = _read_env_file(root / ".env")
    api_key = os.getenv("DEEPSEEK_API_KEY", env_values.get("DEEPSEEK_API_KEY"))
    base_url = os.getenv(
        "DEEPSEEK_BASE_URL",
        env_values.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
    )
    model = os.getenv("DEEPSEEK_MODEL", env_values.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL))
    timeout = float(
        os.getenv(
            "DEEPSEEK_TIMEOUT",
            env_values.get("DEEPSEEK_TIMEOUT", str(DEFAULT_DEEPSEEK_TIMEOUT)),
        )
    )
    retries = max(
        0,
        int(
            os.getenv(
                "DEEPSEEK_RETRIES",
                env_values.get("DEEPSEEK_RETRIES", str(DEFAULT_DEEPSEEK_RETRIES)),
            )
        ),
    )
    storage_value = os.getenv(
        "CODEPILOT_STORAGE_DIR",
        env_values.get("CODEPILOT_STORAGE_DIR", DEFAULT_STORAGE_DIRNAME),
    )
    storage_path = Path(storage_value)
    if storage_path.is_absolute():
        storage_dir = storage_path
    else:
        storage_dir = (root / storage_path).resolve()
    return CodePilotConfig(
        project_root=root,
        deepseek_api_key=api_key,
        deepseek_base_url=base_url.rstrip("/"),
        deepseek_model=model,
        deepseek_timeout=timeout,
        deepseek_retries=retries,
        storage_dir=storage_dir,
    )


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        values[key.strip()] = value.strip()
    return values
