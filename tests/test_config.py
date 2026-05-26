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
    def test_list_campaigns_empty(self, tmp_config):
        config.create_profile("test")
        assert config.list_campaigns() == []

    def test_add_and_list_campaign(self, tmp_config):
        config.create_profile("test")
        config.add_campaign("SaaS Sales", "We do AI", "Try our AI")
        campaigns = config.list_campaigns()
        assert len(campaigns) == 1
        assert campaigns[0]["title"] == "SaaS Sales"
        assert campaigns[0]["description"] == "We do AI"
        assert campaigns[0]["pitch"] == "Try our AI"

    def test_multiple_campaigns(self, tmp_config):
        config.create_profile("test")
        config.add_campaign("Sales", "desc1", "pitch1")
        config.add_campaign("Partner", "desc2", "pitch2")
        campaigns = config.list_campaigns()
        assert len(campaigns) == 2
        assert campaigns[0]["title"] == "Sales"
        assert campaigns[1]["title"] == "Partner"

    def test_delete_campaign(self, tmp_config):
        config.create_profile("test")
        config.add_campaign("Sales", "desc1", "pitch1")
        config.add_campaign("Partner", "desc2", "pitch2")
        config.delete_campaign(0)
        campaigns = config.list_campaigns()
        assert len(campaigns) == 1
        assert campaigns[0]["title"] == "Partner"

    def test_delete_campaign_out_of_range(self, tmp_config):
        config.create_profile("test")
        config.add_campaign("Sales", "desc1", "pitch1")
        config.delete_campaign(5)  # should not crash
        assert len(config.list_campaigns()) == 1

    def test_migrates_old_dict_format(self, tmp_config):
        """Old campaigns were stored as {category: {description, pitch}} dicts."""
        config.create_profile("test")
        # Manually write old format
        cfg = config.load_config()
        cfg["profiles"]["test"]["campaigns"] = {
            "sales": {"description": "We sell stuff", "pitch": "Buy now"},
            "personal": {"description": "Networking", "pitch": "Let's chat"},
        }
        config.save_config(cfg)
        # list_campaigns should migrate
        campaigns = config.list_campaigns()
        assert len(campaigns) == 2
        titles = [c["title"] for c in campaigns]
        assert "Sales" in titles
        assert "Personal" in titles


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

    def test_migrate_api_keys_to_providers(self, tmp_config):
        """Old config with api_keys but no providers should auto-migrate."""
        old = {
            "name": "Test",
            "email": "t@t.com",
            "api_keys": {"anthropic": "sk-ant-123"},
            "active_profile": "default",
            "profiles": {"default": {"company": "", "role": "", "bio": "", "pitch": "", "color": 75}},
        }
        tmp_config.write_text(json.dumps(old))
        cfg = config.load_config()
        assert "providers" in cfg
        assert "anthropic" in cfg["providers"]
        assert cfg["providers"]["anthropic"]["type"] == "anthropic"
        assert cfg["providers"]["anthropic"]["api_key"] == "sk-ant-123"
        assert cfg["default_provider"] == "anthropic"


class TestProviders:
    def test_add_provider(self, tmp_config):
        config.add_provider("anthropic", "anthropic", "sk-ant-test", "claude-sonnet-4-6")
        providers = config.get_providers()
        assert "anthropic" in providers
        assert providers["anthropic"]["type"] == "anthropic"
        assert providers["anthropic"]["api_key"] == "sk-ant-test"
        assert providers["anthropic"]["default_model"] == "claude-sonnet-4-6"

    def test_add_provider_sets_default_if_first(self, tmp_config):
        config.add_provider("openai", "openai", "sk-test", "gpt-4o")
        assert config.get_default_provider_name() == "openai"

    def test_add_proxy_with_base_url(self, tmp_config):
        config.add_provider("hf", "proxy", "sk-hf", "llama-3", "https://hf.co/v1")
        prov = config.get_provider("hf")
        assert prov["base_url"] == "https://hf.co/v1"
        assert prov["type"] == "proxy"

    def test_remove_provider(self, tmp_config):
        config.add_provider("anthropic", "anthropic", "sk-ant", "claude-sonnet-4-6")
        config.add_provider("openai", "openai", "sk-oai", "gpt-4o")
        config.remove_provider("openai")
        assert "openai" not in config.get_providers()

    def test_remove_default_picks_new_default(self, tmp_config):
        config.add_provider("anthropic", "anthropic", "sk-ant", "claude-sonnet-4-6")
        config.add_provider("openai", "openai", "sk-oai", "gpt-4o")
        config.set_default_provider("openai")
        config.remove_provider("openai")
        assert config.get_default_provider_name() == "anthropic"

    def test_remove_nonexistent_raises(self, tmp_config):
        with pytest.raises(KeyError):
            config.remove_provider("nope")

    def test_set_default_provider(self, tmp_config):
        config.add_provider("anthropic", "anthropic", "sk-ant", "claude-sonnet-4-6")
        config.add_provider("openai", "openai", "sk-oai", "gpt-4o")
        config.set_default_provider("openai")
        assert config.get_default_provider_name() == "openai"

    def test_set_default_nonexistent_raises(self, tmp_config):
        with pytest.raises(KeyError):
            config.set_default_provider("nope")

    def test_get_api_key_from_providers(self, tmp_config):
        config.add_provider("anthropic", "anthropic", "sk-from-provider", "claude-sonnet-4-6")
        assert config.get_api_key("anthropic") == "sk-from-provider"

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


class TestSmtp:
    def test_no_smtp_returns_none(self, tmp_config):
        assert config.get_smtp() is None

    def test_set_and_get_smtp(self, tmp_config):
        config.set_smtp(
            host="smtp.gmail.com",
            port=587,
            username="user@gmail.com",
            password="app-password",
            sender_email="user@gmail.com",
            sender_name="Test User",
            use_tls=True,
        )
        smtp = config.get_smtp()
        assert smtp is not None
        assert smtp["host"] == "smtp.gmail.com"
        assert smtp["port"] == 587
        assert smtp["username"] == "user@gmail.com"
        assert smtp["password"] == "app-password"
        assert smtp["sender_email"] == "user@gmail.com"
        assert smtp["sender_name"] == "Test User"
        assert smtp["use_tls"] is True

    def test_smtp_persists_across_loads(self, tmp_config):
        config.set_smtp("smtp.test.com", 465, "u", "p", "u@t.com")
        # Force reload
        smtp = config.get_smtp()
        assert smtp["host"] == "smtp.test.com"
        assert smtp["port"] == 465
