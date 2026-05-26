"""Configuration management for OpenCold.

Data model:
  Top-level identity (shared): name, email, api_keys
  Profiles (different hats):   company, role, bio, pitch, color
"""

import json
import random
from pathlib import Path

CONFIG_DIR = Path.home() / ".opencold"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_PROFILE = "default"

# 256-color ANSI palette for profiles
PROFILE_PALETTE = [
    204,  # rose
    114,  # green
    75,   # sky blue
    215,  # orange
    141,  # lavender
    73,   # teal
    210,  # coral
    228,  # pale yellow
    183,  # lilac
    108,  # sage
    167,  # brick red
    45,   # bright cyan
]


def _ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _empty_config() -> dict:
    return {
        "name": "",
        "email": "",
        "api_keys": {},
        "providers": {},
        "default_provider": "",
        "active_profile": DEFAULT_PROFILE,
        "profiles": {},
    }


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return _empty_config()
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return _migrate(cfg)


def _migrate(cfg: dict) -> dict:
    """Migrate from old profile-centric format to identity+hats format."""
    # Already new format
    if "name" in cfg and "profiles" in cfg:
        # Migrate api_keys → providers if not done yet
        if "providers" not in cfg and cfg.get("api_keys"):
            cfg["providers"] = {}
            for name, key in cfg["api_keys"].items():
                ptype = "anthropic" if "anthropic" in name else (
                    "openai" if "openai" in name else "proxy"
                )
                default_model = "claude-sonnet-4-6" if ptype == "anthropic" else (
                    "gpt-4o" if ptype == "openai" else ""
                )
                cfg["providers"][name] = {
                    "type": ptype,
                    "api_key": key,
                    "default_model": default_model,
                }
            cfg["default_provider"] = "anthropic" if "anthropic" in cfg["providers"] else (
                next(iter(cfg["providers"]), "")
            )
            save_config(cfg)
        return cfg

    # Old format: profiles held full_name, email, api_keys per profile
    if "profiles" in cfg:
        old_active = cfg.get("active_profile", DEFAULT_PROFILE)
        old_profiles = cfg.get("profiles", {})

        # Extract identity from the first profile that has it
        identity_source = old_profiles.get(old_active, {})
        if not identity_source:
            identity_source = next(iter(old_profiles.values()), {})

        new = {
            "name": identity_source.get("full_name", ""),
            "email": identity_source.get("email", ""),
            "api_keys": identity_source.get("api_keys", {}),
            "active_profile": old_active,
            "profiles": {},
        }

        for pname, pdata in old_profiles.items():
            new["profiles"][pname] = {
                "company": pdata.get("company", ""),
                "role": pdata.get("role", ""),
                "bio": "",
                "pitch": "",
                "color": pdata.get("color") or random.choice(PROFILE_PALETTE),
            }
            # Merge any api_keys from other profiles
            for provider, key in pdata.get("api_keys", {}).items():
                if provider not in new["api_keys"]:
                    new["api_keys"][provider] = key

        save_config(new)
        return new

    # Very old flat format
    new = _empty_config()
    old_profile = cfg.get("profile", {})
    new["name"] = old_profile.get("full_name", "")
    new["email"] = old_profile.get("email", "")
    new["api_keys"] = cfg.get("api_keys", {})
    new["profiles"][DEFAULT_PROFILE] = {
        "company": old_profile.get("company", ""),
        "role": old_profile.get("role", ""),
        "bio": "",
        "pitch": "",
        "color": random.choice(PROFILE_PALETTE),
    }
    save_config(new)
    return new


def save_config(cfg: dict) -> None:
    _ensure_dir()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def config_exists() -> bool:
    if not CONFIG_FILE.exists():
        return False
    cfg = load_config()
    return bool(cfg.get("name")) or bool(cfg.get("api_keys"))


# ── identity (top-level, shared) ─────────────────────────────────────────────


def get_identity() -> dict:
    cfg = load_config()
    return {"name": cfg.get("name", ""), "email": cfg.get("email", "")}


def set_identity(name: str | None = None, email: str | None = None) -> None:
    cfg = load_config()
    if name is not None:
        cfg["name"] = name
    if email is not None:
        cfg["email"] = email
    save_config(cfg)


# ── API keys (top-level, shared) ─────────────────────────────────────────────


def get_api_key(provider: str = "anthropic") -> str | None:
    cfg = load_config()
    # New format first
    prov = cfg.get("providers", {}).get(provider)
    if prov:
        return prov.get("api_key")
    # Legacy fallback
    return cfg.get("api_keys", {}).get(provider)


def set_api_key(provider: str, key: str) -> None:
    cfg = load_config()
    cfg.setdefault("api_keys", {})[provider] = key
    save_config(cfg)


def get_all_api_keys() -> dict:
    return dict(load_config().get("api_keys", {}))


# ── providers ────────────────────────────────────────────────────────────────

PROVIDER_TYPES = ("anthropic", "openai", "proxy")

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "proxy": "",
}


def get_providers() -> dict:
    """Return all configured providers."""
    return dict(load_config().get("providers", {}))


def get_provider(name: str) -> dict | None:
    """Return a single provider's config dict."""
    return load_config().get("providers", {}).get(name)


def add_provider(name: str, provider_type: str, api_key: str,
                 default_model: str = "", base_url: str = "",
                 max_tokens: int = 0) -> None:
    """Add or update a provider."""
    cfg = load_config()
    entry = {
        "type": provider_type,
        "api_key": api_key,
        "default_model": default_model or DEFAULT_MODELS.get(provider_type, ""),
    }
    if base_url:
        entry["base_url"] = base_url
    if max_tokens:
        entry["max_tokens"] = max_tokens
    cfg.setdefault("providers", {})[name] = entry
    # Also write to legacy api_keys for backward compat
    cfg.setdefault("api_keys", {})[name] = api_key
    # Set as default if it's the first provider
    if not cfg.get("default_provider"):
        cfg["default_provider"] = name
    save_config(cfg)


def remove_provider(name: str) -> None:
    """Remove a provider by name."""
    cfg = load_config()
    providers = cfg.get("providers", {})
    if name not in providers:
        raise KeyError(f"Provider '{name}' does not exist.")
    del providers[name]
    cfg.get("api_keys", {}).pop(name, None)
    if cfg.get("default_provider") == name:
        cfg["default_provider"] = next(iter(providers), "")
    save_config(cfg)


def get_default_provider_name() -> str:
    """Return the name of the default provider."""
    return load_config().get("default_provider", "") or "anthropic"


def set_default_provider(name: str) -> None:
    """Set the default provider."""
    cfg = load_config()
    if name not in cfg.get("providers", {}):
        raise KeyError(f"Provider '{name}' does not exist.")
    cfg["default_provider"] = name
    save_config(cfg)


# ── active profile ───────────────────────────────────────────────────────────


def get_active_profile_name() -> str:
    return load_config().get("active_profile", DEFAULT_PROFILE)


def set_active_profile(name: str) -> None:
    cfg = load_config()
    if name not in cfg.get("profiles", {}):
        raise KeyError(f"Profile '{name}' does not exist.")
    cfg["active_profile"] = name
    save_config(cfg)


# ── profile CRUD ─────────────────────────────────────────────────────────────


def list_profiles() -> list[str]:
    return list(load_config().get("profiles", {}).keys())


def _pick_color(cfg: dict) -> int:
    used = {p.get("color") for p in cfg.get("profiles", {}).values()}
    available = [c for c in PROFILE_PALETTE if c not in used]
    return random.choice(available) if available else random.choice(PROFILE_PALETTE)


def create_profile(name: str) -> None:
    cfg = load_config()
    color = _pick_color(cfg)
    cfg.setdefault("profiles", {})[name] = {
        "company": "",
        "role": "",
        "bio": "",
        "pitch": "",
        "color": color,
    }
    cfg["active_profile"] = name
    save_config(cfg)


def delete_profile(name: str) -> None:
    cfg = load_config()
    profiles = cfg.get("profiles", {})
    if name not in profiles:
        raise KeyError(f"Profile '{name}' does not exist.")
    if len(profiles) == 1:
        raise ValueError("Cannot delete the only profile.")
    del profiles[name]
    if cfg.get("active_profile") == name:
        cfg["active_profile"] = next(iter(profiles))
    save_config(cfg)


# ── profile getters/setters (operate on active profile) ─────────────────────


def get_profile() -> dict:
    """Return active profile data (company, role, bio, pitch)."""
    cfg = load_config()
    name = cfg.get("active_profile", DEFAULT_PROFILE)
    p = dict(cfg.get("profiles", {}).get(name, {}))
    p.pop("color", None)
    return p


def get_profile_data(name: str) -> dict:
    """Return a specific profile's raw data."""
    return dict(load_config().get("profiles", {}).get(name, {}))


def set_profile(
    company: str | None = None,
    role: str | None = None,
    bio: str | None = None,
    pitch: str | None = None,
) -> None:
    cfg = load_config()
    name = cfg.get("active_profile", DEFAULT_PROFILE)
    profile = cfg["profiles"].setdefault(name, {"color": _pick_color(cfg)})
    if company is not None:
        profile["company"] = company
    if role is not None:
        profile["role"] = role
    if bio is not None:
        profile["bio"] = bio
    if pitch is not None:
        profile["pitch"] = pitch
    save_config(cfg)


# ── profile colors ──────────────────────────────────────────────────────────


def get_profile_color(name: str | None = None) -> int:
    cfg = load_config()
    if name is None:
        name = cfg.get("active_profile", DEFAULT_PROFILE)
    profile = cfg.get("profiles", {}).get(name, {})
    color = profile.get("color")
    if color is None:
        color = _pick_color(cfg)
        profile["color"] = color
        save_config(cfg)
    return color


def color_ansi(code: int) -> str:
    return f"\033[38;5;{code}m"


# ── campaigns (per profile) ─────────────────────────────────────────────────


def _migrate_campaigns(profile: dict) -> list[dict]:
    """Migrate old dict-format campaigns to new list format."""
    raw = profile.get("campaigns", [])
    if isinstance(raw, dict):
        # Old format: {"sales": {"description": "...", "pitch": "..."}, ...}
        migrated = []
        for key, val in raw.items():
            if isinstance(val, dict):
                migrated.append({
                    "title": key.capitalize(),
                    "description": val.get("description", ""),
                    "pitch": val.get("pitch", ""),
                })
        profile["campaigns"] = migrated
        return migrated
    return list(raw)


def list_campaigns() -> list[dict]:
    """Return saved campaigns for the active profile."""
    cfg = load_config()
    name = cfg.get("active_profile", DEFAULT_PROFILE)
    profile = cfg.get("profiles", {}).get(name, {})
    campaigns = _migrate_campaigns(profile)
    # Save if migration happened
    if isinstance(cfg.get("profiles", {}).get(name, {}).get("campaigns"), dict):
        save_config(cfg)
    return campaigns


def add_campaign(title: str, description: str, pitch: str) -> None:
    """Add a new campaign to the active profile."""
    cfg = load_config()
    name = cfg.get("active_profile", DEFAULT_PROFILE)
    profile = cfg["profiles"].setdefault(name, {"color": _pick_color(cfg)})
    # Migrate old dict format if needed
    _migrate_campaigns(profile)
    campaigns = profile.setdefault("campaigns", [])
    campaigns.append({"title": title, "description": description, "pitch": pitch})
    save_config(cfg)


def delete_campaign(index: int) -> None:
    """Delete a campaign by index from the active profile."""
    cfg = load_config()
    name = cfg.get("active_profile", DEFAULT_PROFILE)
    profile = cfg.get("profiles", {}).get(name, {})
    _migrate_campaigns(profile)
    campaigns = profile.get("campaigns", [])
    if 0 <= index < len(campaigns):
        campaigns.pop(index)
        save_config(cfg)
