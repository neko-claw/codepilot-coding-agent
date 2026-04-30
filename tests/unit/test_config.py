from pathlib import Path

from codepilot.core.config import CodePilotConfig, load_config


def test_load_config_reads_project_env_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DEEPSEEK_API_KEY=test-key\n"
        "DEEPSEEK_MODEL=deepseek-chat\n"
        "DEEPSEEK_TIMEOUT=9.5\n"
        "DEEPSEEK_RETRIES=3\n"
        "CODEPILOT_STORAGE_DIR=.codepilot-data\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.deepseek_api_key == "test-key"
    assert config.deepseek_base_url == "https://api.deepseek.com/v1"
    assert config.deepseek_model == "deepseek-chat"
    assert config.deepseek_timeout == 9.5
    assert config.deepseek_retries == 3
    assert config.storage_dir == tmp_path / ".codepilot-data"


def test_load_config_uses_defaults_when_env_file_missing(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.deepseek_api_key is None
    assert config.deepseek_base_url == "https://api.deepseek.com/v1"
    assert config.deepseek_model == "deepseek-chat"
    assert config.deepseek_timeout == 15.0
    assert config.deepseek_retries == 2
    assert config.storage_dir == tmp_path / ".codepilot"


def test_config_detects_api_enablement() -> None:
    disabled = CodePilotConfig(
        project_root=Path("/tmp/project"),
        deepseek_api_key=None,
        deepseek_base_url="https://api.deepseek.com/v1",
        deepseek_model="deepseek-chat",
        deepseek_timeout=15.0,
        deepseek_retries=2,
        storage_dir=Path("/tmp/project/.codepilot"),
    )
    enabled = CodePilotConfig(
        project_root=Path("/tmp/project"),
        deepseek_api_key="secret",
        deepseek_base_url="https://api.deepseek.com/v1",
        deepseek_model="deepseek-chat",
        deepseek_timeout=15.0,
        deepseek_retries=2,
        storage_dir=Path("/tmp/project/.codepilot"),
    )

    assert disabled.deepseek_enabled is False
    assert enabled.deepseek_enabled is True
