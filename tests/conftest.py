"""Shared fixtures for opencold tests."""

import json
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Redirect config to a temp directory so tests don't touch real config."""
    config_dir = tmp_path / ".opencold"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    from opencold import config
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    return config_file


@pytest.fixture
def seeded_config(tmp_config):
    """A tmp config pre-populated with identity, API key, and a profile."""
    cfg = {
        "name": "Test User",
        "email": "test@example.com",
        "api_keys": {"anthropic": "sk-ant-test-key-1234567890"},
        "active_profile": "default",
        "profiles": {
            "default": {
                "company": "TestCo",
                "role": "Engineer",
                "bio": "I build things",
                "pitch": "Let's build together",
                "color": 75,
            }
        },
    }
    tmp_config.write_text(json.dumps(cfg, indent=2))
    return tmp_config


@pytest.fixture
def test_csv():
    return str(FIXTURES_DIR / "test_input.csv")


@pytest.fixture
def test_csv_no_website():
    return str(FIXTURES_DIR / "test_input_no_website.csv")
