"""Tests for config module."""

import json
import pytest
from opencold import config


class TestIdentity:
    def test_get_identity_empty(self, tmp_config):
        identity = config.get_identity()
        assert identity == {"name": "", "email": ""}

    def test_set_and_get_identity(self, tmp_config):
        config.set_identity(name="Alice", email="alice@test.com")
        identity = config.get_identity()
        assert identity["name"] == "Alice"
        assert identity["email"] == "alice@test.com"

    def test_set_identity_partial(self, tmp_config):
        config.set_identity(name="Alice")
        config.set_identity(email="alice@test.com")
        identity = config.get_identity()
        assert identity["name"] == "Alice"
        assert identity["email"] == "alice@test.com"


class TestApiKeys:
    def test_no_key_returns_none(self, tmp_config):
        assert config.get_api_key("anthropic") is None

    def test_set_and_get_key(self, tmp_config):
        config.set_api_key("anthropic", "sk-test-123")
        assert config.get_api_key("anthropic") == "sk-test-123"

    def test_multiple_providers(self, tmp_config):
        config.set_api_key("anthropic", "sk-ant")
        config.set_api_key("openai", "sk-oai")
        keys = config.get_all_api_keys()
        assert keys == {"anthropic": "sk-ant", "openai": "sk-oai"}


class TestProfiles:
    def test_create_and_list(self, tmp_config):
        config.create_profile("work")
        assert "work" in config.list_profiles()

    def test_create_sets_active(self, tmp_config):
        config.create_profile("work")
        assert config.get_active_profile_name() == "work"

    def test_switch_profile(self, tmp_config):
        config.create_profile("a")
        config.create_profile("b")
        config.set_active_profile("a")
        assert config.get_active_profile_name() == "a"

    def test_switch_nonexistent_raises(self, tmp_config):
        config.create_profile("a")
        with pytest.raises(KeyError):
            config.set_active_profile("nope")

    def test_delete_profile(self, tmp_config):
        config.create_profile("a")
        config.create_profile("b")
        config.delete_profile("a")
        assert "a" not in config.list_profiles()

    def test_delete_only_profile_raises(self, tmp_config):
        config.create_profile("only")
        with pytest.raises(ValueError):
            config.delete_profile("only")

    def test_delete_active_switches(self, tmp_config):
        config.create_profile("a")
        config.create_profile("b")
        config.set_active_profile("b")
        config.delete_profile("b")
        assert config.get_active_profile_name() == "a"

    def test_set_profile_fields(self, tmp_config):
        config.create_profile("dev")
        config.set_profile(company="Acme", role="Dev", bio="I code", pitch="Let's go")
        prof = config.get_profile()
        assert prof["company"] == "Acme"
        assert prof["role"] == "Dev"
        assert prof["bio"] == "I code"
        assert prof["pitch"] == "Let's go"

    def test_profile_color_assigned(self, tmp_config):
        config.create_profile("test")
        color = config.get_profile_color("test")
        assert isinstance(color, int)
        assert color in config.PROFILE_PALETTE


class TestCampaigns:
    def test_get_campaign_empty(self, tmp_config):
        config.create_profile("test")
        assert config.get_campaign("sales") is None

    def test_set_and_get_campaign(self, tmp_config):
        config.create_profile("test")
        ctx = {"description": "We do X", "pitch": "Try X"}
        config.set_campaign("sales", ctx)
        assert config.get_campaign("sales") == ctx

    def test_campaigns_per_category(self, tmp_config):
        config.create_profile("test")
        config.set_campaign("sales", {"description": "sales stuff", "pitch": "buy"})
        config.set_campaign("personal", {"description": "personal stuff", "pitch": "hi"})
        assert config.get_campaign("sales")["description"] == "sales stuff"
        assert config.get_campaign("personal")["description"] == "personal stuff"


class TestMigration:
    def test_migrate_old_flat_format(self, tmp_config):
        old = {
            "profile": {
                "full_name": "Old User",
                "email": "old@test.com",
                "company": "OldCo",
                "role": "Dev",
            },
            "api_keys": {"anthropic": "sk-old"},
        }
        tmp_config.write_text(json.dumps(old))
        cfg = config.load_config()
        assert cfg["name"] == "Old User"
        assert cfg["email"] == "old@test.com"
        assert cfg["api_keys"]["anthropic"] == "sk-old"
        assert "default" in cfg["profiles"]
        assert cfg["profiles"]["default"]["company"] == "OldCo"

    def test_migrate_old_multi_profile_format(self, tmp_config):
        old = {
            "active_profile": "work",
            "profiles": {
                "work": {
                    "full_name": "Multi User",
                    "email": "multi@test.com",
                    "company": "WorkCo",
                    "role": "PM",
                    "api_keys": {"anthropic": "sk-multi"},
                }
            },
        }
        tmp_config.write_text(json.dumps(old))
        cfg = config.load_config()
        assert cfg["name"] == "Multi User"
        assert cfg["api_keys"]["anthropic"] == "sk-multi"
        assert cfg["profiles"]["work"]["company"] == "WorkCo"

    def test_new_format_untouched(self, tmp_config):
        new = {
            "name": "New User",
            "email": "new@test.com",
            "api_keys": {},
            "active_profile": "default",
            "profiles": {"default": {"company": "", "role": "", "bio": "", "pitch": "", "color": 75}},
        }
        tmp_config.write_text(json.dumps(new))
        cfg = config.load_config()
        assert cfg["name"] == "New User"


class TestConfigExists:
    def test_empty_config_not_exists(self, tmp_config):
        assert config.config_exists() is False

    def test_with_name_exists(self, tmp_config):
        config.set_identity(name="Someone")
        assert config.config_exists() is True

    def test_with_api_key_exists(self, tmp_config):
        config.set_api_key("anthropic", "sk-test")
        assert config.config_exists() is True
