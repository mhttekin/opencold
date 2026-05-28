"""OpenCold CLI — cold outreach email generator powered by Claude."""

import csv
import json
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.completion import PathCompleter, Completer, Completion
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl

from opencold import config, crawler, generator, sender
from opencold.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    build_template_prompt,
)

app = typer.Typer(
    name="opencold",
    help="Generate personalized cold outreach emails using Claude API.",
    invoke_without_command=True,
)
config_app = typer.Typer(help="Manage API keys and user profile.", invoke_without_command=True)
app.add_typer(config_app, name="config")
profile_app = typer.Typer(help="Manage named profiles.")
app.add_typer(profile_app, name="profile")
provider_app = typer.Typer(help="Manage LLM providers.")
app.add_typer(provider_app, name="provider")


# ── ANSI helpers ─────────────────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"


def _profile_color() -> str:
    code = config.get_profile_color()
    return config.color_ansi(code)


def _prompt_str() -> str:
    name = config.get_active_profile_name()
    pc = _profile_color()
    return f"{DIM}[{pc}\u25cf {name}{RESET}{DIM}]{RESET} opencold> "


def _rprompt_str() -> str:
    """Right-side prompt showing default provider and model."""
    provider_name = config.get_default_provider_name()
    if not provider_name:
        return ""
    prov = config.get_provider(provider_name)
    if not prov:
        return ""
    model = prov.get("default_model", "")
    if model:
        return f"{DIM}{provider_name}:{model}{RESET}"
    return f"{DIM}{provider_name}{RESET}"


# ── ESC-cancellable prompts ─────────────────────────────────────────────────


class Cancelled(Exception):
    """Raised when user presses ESC to cancel a prompt."""


def _esc_bindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("escape", eager=False)
    def _cancel(event):
        event.app.exit(exception=Cancelled())

    return kb


_kb = _esc_bindings()


def _ask(text: str, default: str = "", hide: bool = False) -> str:
    """Prompt for input. Press ESC or Ctrl+C to cancel."""
    suffix = f" [{default}]" if default else ""
    try:
        result = PromptSession(key_bindings=_kb).prompt(
            f"  {text}{suffix}: ", is_password=hide,
        )
        return result.strip() or default
    except KeyboardInterrupt:
        raise Cancelled()


def _confirm(text: str, default: bool = False) -> bool:
    """Yes/no confirmation. Press ESC or Ctrl+C to cancel."""
    yn = "Y/n" if default else "y/N"
    try:
        result = PromptSession(key_bindings=_kb).prompt(f"  {text} [{yn}]: ")
        if not result.strip():
            return default
        return result.strip().lower() in ("y", "yes")
    except KeyboardInterrupt:
        raise Cancelled()


# ── interactive campaign selector ───────────────────────────────────────────


def _truncate(text: str, max_words: int = 22) -> str:
    """Truncate text to max_words, adding '...' if truncated."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def _select_campaign() -> dict | None:
    """Interactive campaign selector with arrow keys.

    Returns the selected campaign dict, or None if cancelled.
    The user can press 'd' to delete a campaign.
    """
    while True:
        campaigns = config.list_campaigns()
        items = [c["title"] for c in campaigns] + ["+ Add new campaign"]
        total = len(items)

        if total == 1:
            # No saved campaigns, go straight to "Add new"
            return _create_campaign()

        selected = [0]
        deleted = [False]

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _up(event):
            selected[0] = (selected[0] - 1) % total

        @kb.add("down")
        @kb.add("j")
        def _down(event):
            selected[0] = (selected[0] + 1) % total

        @kb.add("enter")
        def _select(event):
            event.app.exit(result=selected[0])

        @kb.add("d")
        def _delete(event):
            idx = selected[0]
            if idx < len(campaigns):
                deleted[0] = True
                event.app.exit(result=idx)

        @kb.add("escape")
        @kb.add("q")
        def _quit(event):
            event.app.exit(result=None)

        def _get_text():
            lines = []
            lines.append(("", "\n"))
            lines.append(("bold", "  Select a campaign  "))
            lines.append(("fg:ansibrightblack", "(\u2191\u2193 move, Enter select, d delete, Esc cancel)\n\n"))
            for i, label in enumerate(items):
                is_add_new = i == len(items) - 1
                if i == selected[0]:
                    if is_add_new:
                        lines.append(("fg:green bold", f"  \u25b8 {label}\n"))
                    else:
                        desc = _truncate(campaigns[i].get("description", ""))
                        pitch = _truncate(campaigns[i].get("pitch", ""))
                        lines.append(("fg:cyan bold", f"  \u25b8 {label}\n"))
                        if desc:
                            lines.append(("", f"    {desc}\n"))
                        if pitch:
                            lines.append(("fg:ansibrightblack", f"    {pitch}\n"))
                else:
                    if is_add_new:
                        lines.append(("fg:ansibrightblack", f"    {label}\n"))
                    else:
                        lines.append(("", f"    {label}\n"))
                if not is_add_new and i < len(items) - 2:
                    lines.append(("fg:ansibrightblack", "    ────────────────────────────\n"))
            return FormattedText(lines)

        control = FormattedTextControl(_get_text)
        layout = Layout(Window(content=control, always_hide_cursor=True))
        result = Application(layout=layout, key_bindings=kb, full_screen=False).run()

        if result is None:
            return None

        if deleted[0]:
            idx = result
            title = campaigns[idx]["title"]
            typer.echo(f"\n  Delete campaign '{title}'?")
            if _confirm("Confirm delete", default=False):
                config.delete_campaign(idx)
                typer.echo(f"  Deleted '{title}'.")
            continue  # re-render the menu

        if result == len(campaigns):
            return _create_campaign()

        return campaigns[result]


def _create_campaign() -> dict | None:
    """Prompt user to create a new campaign and save it."""
    typer.echo(f"\n  {BOLD}New campaign{RESET} {DIM}(ESC to cancel){RESET}\n")
    try:
        title = _ask("Campaign title")
        if not title:
            typer.echo(f"  {DIM}Title is required.{RESET}")
            return None
        description = _ask("Briefly describe what you / your company does")
        pitch = _ask("What's the key message or pitch for this outreach?")
        config.add_campaign(title, description, pitch)
        typer.echo(f"\n  Saved campaign '{title}'.")
        return {"title": title, "description": description, "pitch": pitch}
    except Cancelled:
        return None


# ── interactive CSV file selector ───────────────────────────────────────────


def _list_csv_files() -> list[str]:
    """List .csv files in the current directory."""
    return sorted(
        f for f in os.listdir(".")
        if f.lower().endswith(".csv") and os.path.isfile(f)
    )


def _select_proxy_provider(proxy_providers: dict) -> str | None:
    """Interactive selector for proxy providers. Returns provider name or None."""
    names = list(proxy_providers.keys())
    total = len(names)
    selected = [0]

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        selected[0] = (selected[0] - 1) % total

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        selected[0] = (selected[0] + 1) % total

    @kb.add("enter")
    def _select(event):
        event.app.exit(result=selected[0])

    @kb.add("escape")
    @kb.add("q")
    def _quit(event):
        event.app.exit(result=None)

    def _get_text():
        lines = []
        lines.append(("", "\n"))
        lines.append(("bold", "  Select proxy provider"))
        lines.append(("", f"  {DIM}(↑↓ move, Enter select, Esc cancel){RESET}\n\n"))
        for i, name in enumerate(names):
            prov = proxy_providers[name]
            base = prov.get("base_url", "")
            detail = f" {DIM}({base}){RESET}" if base else ""
            if i == selected[0]:
                lines.append(("fg:cyan bold", f"  ▸ {name}"))
                lines.append(("", f"{detail}\n"))
            else:
                lines.append(("", f"    {name}{detail}\n"))
        return FormattedText(lines)

    control = FormattedTextControl(_get_text)
    layout = Layout(Window(content=control, always_hide_cursor=True))
    result = Application(layout=layout, key_bindings=kb, full_screen=False).run()

    if result is None:
        return None
    return names[result]


def _select_csv_file() -> str | None:
    """Interactive file selector for CSV files with arrow keys."""
    csv_files = _list_csv_files()
    if not csv_files:
        typer.echo(f"  {DIM}No .csv files found in the current directory.{RESET}")
        return None

    selected = [0]
    total = len(csv_files)

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        selected[0] = (selected[0] - 1) % total

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        selected[0] = (selected[0] + 1) % total

    @kb.add("enter")
    def _select(event):
        event.app.exit(result=selected[0])

    @kb.add("escape")
    @kb.add("q")
    def _quit(event):
        event.app.exit(result=None)

    def _get_text():
        lines = []
        lines.append(("", "\n"))
        lines.append(("bold", "  Select a CSV file  "))
        lines.append(("fg:ansibrightblack", "(\u2191\u2193 move, Enter select, Esc cancel)\n\n"))
        for i, fname in enumerate(csv_files):
            try:
                size = os.path.getsize(fname)
                size_str = f"{size:,} bytes" if size < 1024 else f"{size / 1024:.1f} KB"
            except OSError:
                size_str = ""
            if i == selected[0]:
                lines.append(("fg:cyan bold", f"  \u25b8 {fname}"))
                if size_str:
                    lines.append(("fg:ansibrightblack", f"  ({size_str})"))
                lines.append(("", "\n"))
            else:
                lines.append(("", f"    {fname}"))
                if size_str:
                    lines.append(("fg:ansibrightblack", f"  ({size_str})"))
                lines.append(("", "\n"))
        return FormattedText(lines)

    control = FormattedTextControl(_get_text)
    layout = Layout(Window(content=control, always_hide_cursor=True))
    result = Application(layout=layout, key_bindings=kb, full_screen=False).run()

    if result is None:
        return None
    return csv_files[result]


# ── REPL completer ──────────────────────────────────────────────────────────


class _ReplCompleter(Completer):
    """Tab-completer for the REPL: completes commands and file paths."""

    _TOP_COMMANDS = ["run", "send", "smtp", "config", "profile", "provider", "help", "exit", "q"]
    _CONFIG_SUBS = ["init", "set-key"]
    _PROFILE_SUBS = ["list", "create", "use", "delete"]
    _PROVIDER_SUBS = ["list", "add", "delete", "default"]
    _SMTP_SUBS = ["setup", "test", "show"]
    # Subcommands that accept a name as 3rd argument
    _PROFILE_NAME_SUBS = {"use", "delete"}
    _PROVIDER_NAME_SUBS = {"delete", "default"}

    def __init__(self):
        self._path_completer = PathCompleter(
            expanduser=True,
            file_filter=lambda name: name.lower().endswith(".csv") or os.path.isdir(name),
        )

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()

        # Complete top-level commands when typing the first word
        if len(words) == 0 or (len(words) == 1 and not text.endswith(" ")):
            word = words[0] if words else ""
            for cmd in self._TOP_COMMANDS:
                if cmd.startswith(word.lower()) and cmd != word.lower():
                    yield Completion(cmd, start_position=-len(word))
            return

        first = words[0].lower()

        # Subcommands for "config"
        if first == "config":
            # Only complete subcommand (2nd word), nothing after
            if len(words) == 2 and not text.endswith(" "):
                sub = words[1]
                for s in self._CONFIG_SUBS:
                    if s.startswith(sub.lower()) and s != sub.lower():
                        yield Completion(s, start_position=-len(sub))
            elif len(words) == 1 and text.endswith(" "):
                for s in self._CONFIG_SUBS:
                    yield Completion(s)
            return

        # Subcommands for "profile"
        if first == "profile":
            # Complete subcommand (2nd word)
            if len(words) == 2 and not text.endswith(" "):
                sub = words[1]
                for s in self._PROFILE_SUBS:
                    if s.startswith(sub.lower()) and s != sub.lower():
                        yield Completion(s, start_position=-len(sub))
            elif len(words) == 1 and text.endswith(" "):
                for s in self._PROFILE_SUBS:
                    yield Completion(s)
            # Complete profile names for "use" and "delete"
            elif len(words) >= 2:
                sub = words[1].lower()
                if sub in self._PROFILE_NAME_SUBS:
                    partial = words[2] if len(words) == 3 and not text.endswith(" ") else ""
                    if len(words) <= 3:
                        for name in config.list_profiles():
                            if name.startswith(partial) and name != partial:
                                yield Completion(name, start_position=-len(partial))
            return

        # Subcommands for "provider"
        if first == "provider":
            if len(words) == 2 and not text.endswith(" "):
                sub = words[1]
                for s in self._PROVIDER_SUBS:
                    if s.startswith(sub.lower()) and s != sub.lower():
                        yield Completion(s, start_position=-len(sub))
            elif len(words) == 1 and text.endswith(" "):
                for s in self._PROVIDER_SUBS:
                    yield Completion(s)
            # Complete provider names for "delete" and "default"
            elif len(words) >= 2:
                sub = words[1].lower()
                if sub in self._PROVIDER_NAME_SUBS:
                    partial = words[2] if len(words) == 3 and not text.endswith(" ") else ""
                    if len(words) <= 3:
                        for name in config.get_providers().keys():
                            if name.startswith(partial) and name != partial:
                                yield Completion(name, start_position=-len(partial))
            return

        # After "run", complete file paths and --flags
        if first == "run":
            current_word = words[-1] if not text.endswith(" ") else ""
            # Suggest --flags when user starts typing with -
            if current_word.startswith("-"):
                run_flags = [
                    "--model", "--max-tokens", "--output", "--format",
                    "--system-prompt", "--template", "--delay", "--send",
                ]
                for flag in run_flags:
                    if flag.startswith(current_word) and flag != current_word:
                        yield Completion(flag, start_position=-len(current_word))
                return
            # Otherwise complete file paths (CSV files)
            prefix_len = len(words[0]) + 1
            from prompt_toolkit.document import Document
            sub_text = text[prefix_len:] if len(text) > prefix_len else ""
            sub_doc = Document(sub_text)
            yield from self._path_completer.get_completions(sub_doc, complete_event)

        # After "send", complete file paths and --flags
        if first == "send":
            current_word = words[-1] if not text.endswith(" ") else ""
            if current_word.startswith("-"):
                for flag in ["--subject"]:
                    if flag.startswith(current_word) and flag != current_word:
                        yield Completion(flag, start_position=-len(current_word))
                return
            prefix_len = len(words[0]) + 1
            from prompt_toolkit.document import Document
            sub_text = text[prefix_len:] if len(text) > prefix_len else ""
            sub_doc = Document(sub_text)
            yield from self._path_completer.get_completions(sub_doc, complete_event)

        # Subcommands for "smtp"
        if first == "smtp":
            if len(words) == 2 and not text.endswith(" "):
                sub = words[1]
                for s in self._SMTP_SUBS:
                    if s.startswith(sub.lower()) and s != sub.lower():
                        yield Completion(s, start_position=-len(sub))
            elif len(words) == 1 and text.endswith(" "):
                for s in self._SMTP_SUBS:
                    yield Completion(s)
            return


# ── config commands ──────────────────────────────────────────────────────────


@config_app.command("init")
def config_init() -> None:
    """Interactive setup: identity, API key, and active profile."""
    typer.echo(f"OpenCold setup {DIM}(press ESC to cancel){RESET}\n")

    # ── Identity (shared across all profiles) ──
    typer.echo(f"  {BOLD}Identity{RESET} {DIM}(shared across all profiles){RESET}\n")
    identity = config.get_identity()
    name = _ask("Your name", default=identity.get("name", ""))
    email = _ask("Your email", default=identity.get("email", ""))
    config.set_identity(name=name, email=email)

    # ── API key ──
    typer.echo(f"\n  {BOLD}API Key{RESET}\n")
    existing_key = config.get_api_key("anthropic")
    if existing_key:
        masked = existing_key[:8] + "..." + existing_key[-4:]
        typer.echo(f"  Anthropic API key already set ({masked}).")
        if _confirm("Overwrite?", default=False):
            key = _ask("Anthropic API key", hide=True)
            config.set_api_key("anthropic", key)
            typer.echo("  API key saved.")
    else:
        key = _ask("Anthropic API key", hide=True)
        config.set_api_key("anthropic", key)
        typer.echo("  API key saved.")

    # ── Active profile (hat) ──
    profile_name = config.get_active_profile_name()
    pc = config.color_ansi(config.get_profile_color(profile_name))
    typer.echo(f"\n  {BOLD}Profile{RESET} {pc}\u25cf {profile_name}{RESET} {DIM}(company, role, bio, pitch){RESET}\n")
    prof = config.get_profile()
    company = _ask("Company", default=prof.get("company", ""))
    role = _ask("Role / title", default=prof.get("role", ""))
    bio = _ask("Bio (brief description of what you do)", default=prof.get("bio", ""))
    pitch = _ask("Default pitch / key message", default=prof.get("pitch", ""))

    config.set_profile(company=company, role=role, bio=bio, pitch=pitch)
    typer.echo(f"\n  Config saved to {config.CONFIG_FILE}")


@config_app.callback(invoke_without_command=True)
def config_show(ctx: typer.Context = None) -> None:
    """Show current configuration (or run a subcommand)."""
    if ctx is not None and ctx.invoked_subcommand is not None:
        return
    if not config.config_exists():
        typer.echo("No config found. Run: config init")
        return
    cfg = config.load_config()
    active = cfg.get("active_profile", "")
    profiles = cfg.get("profiles", {})

    typer.echo(f"\n  {BOLD}OpenCold Configuration{RESET}")
    typer.echo(f"  {DIM}{config.CONFIG_FILE}{RESET}\n")

    # ── Identity (shared) ──
    typer.echo(f"  {BOLD}Identity{RESET}")
    typer.echo(f"  {DIM}{'─' * 36}{RESET}")
    name = cfg.get("name", "")
    email_val = cfg.get("email", "")
    if name:
        typer.echo(f"    {DIM}Name{RESET}     {name}")
    if email_val:
        typer.echo(f"    {DIM}Email{RESET}    {email_val}")
    if not name and not email_val:
        typer.echo(f"    {DIM}(not set — run config init){RESET}")

    # ── API Keys (shared) ──
    keys = cfg.get("api_keys", {})
    typer.echo("")
    if keys:
        for provider, key in keys.items():
            masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
            check = f"{GREEN}\u2713{RESET}"
            typer.echo(f"    {check} {DIM}{provider}{RESET}  {DIM}{masked}{RESET}")
    else:
        typer.echo(f"    {YELLOW}\u26a0{RESET} {DIM}No API keys configured{RESET}")

    # ── Profiles ──
    typer.echo(f"\n  {BOLD}Profiles{RESET}\n")
    for pname, pdata in profiles.items():
        pc = config.color_ansi(pdata.get("color", 75))
        is_active = pname == active
        tag = f"  {BOLD}{GREEN}active{RESET}" if is_active else ""
        typer.echo(f"  {pc}\u25cf {BOLD}{pname}{RESET}{tag}")
        typer.echo(f"  {DIM}{'─' * 36}{RESET}")

        company = pdata.get("company", "")
        role = pdata.get("role", "")
        bio = pdata.get("bio", "")
        pitch = pdata.get("pitch", "")

        if company or role or bio or pitch:
            if company:
                typer.echo(f"    {DIM}Company{RESET}  {company}")
            if role:
                typer.echo(f"    {DIM}Role{RESET}     {role}")
            if bio:
                typer.echo(f"    {DIM}Bio{RESET}      {bio}")
            if pitch:
                typer.echo(f"    {DIM}Pitch{RESET}    {pitch}")
        else:
            typer.echo(f"    {DIM}(empty — run config init to fill in){RESET}")

        # ── Campaigns under this profile ──
        raw_campaigns = pdata.get("campaigns", [])
        if isinstance(raw_campaigns, list) and raw_campaigns:
            typer.echo(f"    {DIM}Campaigns:{RESET}")
            for c in raw_campaigns:
                if isinstance(c, dict):
                    typer.echo(f"      {CYAN}\u25cf{RESET} {c.get('title', '(untitled)')}")
        elif isinstance(raw_campaigns, dict) and raw_campaigns:
            typer.echo(f"    {DIM}Campaigns:{RESET}")
            for key in raw_campaigns:
                typer.echo(f"      {CYAN}\u25cf{RESET} {key.capitalize()}")

        typer.echo("")


@config_app.command("set-key")
def config_set_key(
    provider: str = typer.Argument("anthropic", help="API provider name"),
) -> None:
    """Set an API key for a provider."""
    key = _ask(f"API key for '{provider}'", hide=True)
    config.set_api_key(provider, key)
    typer.echo(f"  API key for '{provider}' saved.")


# ── profile commands ─────────────────────────────────────────────────────────


@profile_app.command("list")
def profile_list() -> None:
    """List all profiles."""
    active = config.get_active_profile_name()
    for name in config.list_profiles():
        color = config.color_ansi(config.get_profile_color(name))
        marker = " *" if name == active else ""
        typer.echo(f"  {color}\u25cf{RESET} {name}{marker}")
    if not config.list_profiles():
        typer.echo("  (none)")


@profile_app.command("create")
def profile_create(name: str = typer.Argument(help="New profile name")) -> None:
    """Create a new profile and switch to it."""
    if name in config.list_profiles():
        typer.echo(f"Profile '{name}' already exists.")
        return
    config.create_profile(name)
    color = config.color_ansi(config.get_profile_color(name))
    typer.echo(f"Created and switched to profile {color}\u25cf {name}{RESET}.\n")

    typer.echo(f"  {DIM}Fill in profile details (ESC to skip){RESET}\n")
    try:
        company = _ask("Company", default="")
        role = _ask("Role / title", default="")
        bio = _ask("Bio (brief description)", default="")
        pitch = _ask("Default pitch / key message", default="")
        config.set_profile(company=company, role=role, bio=bio, pitch=pitch)
    except Cancelled:
        typer.echo(f"\n  {DIM}Skipped — you can fill in later with config init.{RESET}")


@profile_app.command("use")
def profile_use(name: str = typer.Argument(help="Profile to switch to")) -> None:
    """Switch to an existing profile."""
    try:
        config.set_active_profile(name)
        color = config.color_ansi(config.get_profile_color(name))
        typer.echo(f"Switched to profile {color}\u25cf {name}{RESET}.")
    except KeyError:
        typer.echo(f"Profile '{name}' not found. Available: {', '.join(config.list_profiles())}")


@profile_app.command("delete")
def profile_delete(name: str = typer.Argument(help="Profile to delete")) -> None:
    """Delete a profile."""
    try:
        config.delete_profile(name)
        typer.echo(f"Deleted profile '{name}'.")
    except (KeyError, ValueError) as e:
        typer.echo(str(e))


# ── provider commands ────────────────────────────────────────────────────────

_PROVIDER_CHOICES = [
    ("Anthropic", "anthropic", "claude-sonnet-4-6"),
    ("OpenAI", "openai", "gpt-4o"),
    ("Proxy (OpenAI-compatible)", "proxy", ""),
]


def _select_provider_type() -> tuple[str, str, str] | None:
    """Interactive selector for provider type. Returns (label, type, default_model) or None."""
    existing = config.get_providers()
    existing_types = {p.get("type") for p in existing.values()}

    items = []
    for label, ptype, default_model in _PROVIDER_CHOICES:
        # Proxy can be added multiple times, others only once
        already = ptype in existing_types and ptype != "proxy"
        items.append((label, ptype, default_model, already))

    total = len(items)
    selected = [0]

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        selected[0] = (selected[0] - 1) % total

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        selected[0] = (selected[0] + 1) % total

    @kb.add("enter")
    def _select(event):
        event.app.exit(result=selected[0])

    @kb.add("escape")
    @kb.add("q")
    def _quit(event):
        event.app.exit(result=None)

    def _get_text():
        lines = []
        lines.append(("", "\n"))
        lines.append(("bold", "  Select provider:\n\n"))
        for i, (label, ptype, dm, already) in enumerate(items):
            check = f" {GREEN}\u2713{RESET}" if already else ""
            if i == selected[0]:
                lines.append(("fg:cyan bold", f"  \u25b8 {label}"))
                if already:
                    lines.append(("fg:green", " \u2713"))
                lines.append(("", "\n"))
            else:
                lines.append(("", f"    {label}"))
                if already:
                    lines.append(("fg:green", " \u2713"))
                lines.append(("", "\n"))
        return FormattedText(lines)

    control = FormattedTextControl(_get_text)
    layout = Layout(Window(content=control, always_hide_cursor=True))
    result = Application(layout=layout, key_bindings=kb, full_screen=False).run()

    if result is None:
        return None
    label, ptype, default_model, _ = items[result]
    return label, ptype, default_model


@provider_app.command("list")
def provider_list_cmd() -> None:
    """List configured providers and the default."""
    providers = config.get_providers()
    default = config.get_default_provider_name()

    if not providers:
        typer.echo(f"  {DIM}No providers configured. Run: provider add{RESET}")
        return

    for name, prov in providers.items():
        key = prov.get("api_key", "")
        masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        model = prov.get("default_model", "")
        is_default = name == default
        marker = f"  {CYAN}\u2190 default{RESET}" if is_default else ""
        check = f"{GREEN}\u2713{RESET}" if is_default else "\u25cf"
        base_url = prov.get("base_url", "")
        url_info = f"  {DIM}{base_url}{RESET}" if base_url else ""
        typer.echo(f"  {check} {BOLD}{name}{RESET}  {DIM}{masked}{RESET}  ({model}){marker}{url_info}")


@provider_app.command("add")
def provider_add_cmd() -> None:
    """Interactively add a new provider."""
    choice = _select_provider_type()
    if choice is None:
        typer.echo(f"  {DIM}Cancelled.{RESET}")
        return

    label, ptype, suggested_model = choice
    typer.echo("")

    try:
        api_key = _ask("API key", hide=True)
        if not api_key:
            typer.echo(f"  {DIM}API key is required.{RESET}")
            return

        default_model = _ask("Default model", default=suggested_model)

        default_max = "4096" if ptype == "proxy" else "1024"
        max_tokens_str = _ask("Max tokens", default=default_max)
        max_tokens = int(max_tokens_str) if max_tokens_str.isdigit() else int(default_max)

        base_url = ""
        if ptype == "proxy":
            base_url = _ask("Base URL (e.g. https://your-router.com/v1)")
            if not base_url:
                typer.echo(f"  {DIM}Base URL is required for proxy providers.{RESET}")
                return

        # Use type as name for anthropic/openai, ask for title for proxy
        if ptype == "proxy":
            name = _ask("Name for this provider (e.g. huggingface, deepinfra, ollama)")
            if not name:
                typer.echo(f"  {DIM}Name is required.{RESET}")
                return
            name = name.lower().replace(" ", "-")
        else:
            name = ptype

        config.add_provider(name, ptype, api_key, default_model, base_url, max_tokens)
        typer.echo(f"\n  {GREEN}\u2713{RESET} {name} added.")
    except Cancelled:
        typer.echo(f"\n  {DIM}Cancelled.{RESET}")


@provider_app.command("delete")
def provider_delete_cmd(name: str = typer.Argument(help="Provider to delete")) -> None:
    """Delete a configured provider."""
    try:
        prov = config.get_provider(name)
        if not prov:
            typer.echo(f"Provider '{name}' not found.")
            return
        if _confirm(f"Remove {name}?", default=False):
            config.remove_provider(name)
            typer.echo(f"  {GREEN}\u2713{RESET} Removed.")
        else:
            typer.echo(f"  {DIM}Cancelled.{RESET}")
    except Cancelled:
        typer.echo(f"\n  {DIM}Cancelled.{RESET}")


@provider_app.command("default")
def provider_default_cmd(name: str = typer.Argument(help="Provider to set as default")) -> None:
    """Set the default provider for runs."""
    try:
        config.set_default_provider(name)
        prov = config.get_provider(name)
        model = prov.get("default_model", "") if prov else ""
        typer.echo(f"  {GREEN}\u2713{RESET} Default provider set to {BOLD}{name}{RESET} ({model})")
    except KeyError:
        available = ", ".join(config.get_providers().keys())
        typer.echo(f"Provider '{name}' not found. Available: {available}")


# ── shared helpers ───────────────────────────────────────────────────────────


def _ensure_config() -> dict:
    """Ensure config exists; run first-time setup if not."""
    if not config.config_exists():
        typer.echo(f"No config found. Let's set you up. {DIM}(ESC to cancel){RESET}\n")

        # Identity
        name = _ask("Your name")
        email = _ask("Your email")
        config.set_identity(name=name, email=email)

        # API key
        key = _ask("Anthropic API key", hide=True)
        config.set_api_key("anthropic", key)

        # First profile
        profile_name = _ask("Profile name", default="default")
        config.create_profile(profile_name)
        company = _ask("Your company", default="")
        role = _ask("Your role / title", default="")
        bio = _ask("Bio (brief description)", default="")
        pitch = _ask("Default pitch / key message", default="")
        config.set_profile(company=company, role=role, bio=bio, pitch=pitch)

        typer.echo(f"\n  Config saved to {config.CONFIG_FILE}\n")
    return config.load_config()


def _has_enough_context(campaign: dict) -> bool:
    return bool(campaign.get("description") and campaign.get("pitch"))


def _read_csv(path: str) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        typer.echo(f"Error: file '{path}' not found.", err=True)
        raise typer.Exit(1)
    if not rows:
        typer.echo("Error: CSV is empty.", err=True)
        raise typer.Exit(1)
    required = {"email", "first_name", "last_name", "company"}
    missing = required - set(rows[0].keys())
    if missing:
        typer.echo(f"Error: CSV missing columns: {', '.join(missing)}", err=True)
        raise typer.Exit(1)
    return rows


def _validate_csv(rows: list[dict]) -> list[dict] | None:
    """Validate CSV rows for email and website. Returns filtered rows or None to abort."""
    # Check email column — must have at least one valid email
    missing_email = [r for r in rows if not r.get("email", "").strip()]
    if missing_email:
        typer.echo(
            f"\n  {RED}Error:{RESET} {len(missing_email)} row(s) have no email address. "
            f"Cannot proceed without email addresses."
        )
        return None

    # Check website column
    has_website_col = "website" in rows[0]
    if not has_website_col:
        typer.echo(
            f"\n  {YELLOW}Warning:{RESET} No 'website' column found. "
            f"AI will use its own knowledge to personalize emails."
        )
        if not _confirm("Proceed without website data?", default=True):
            return None
        return rows

    # Check how many rows are missing website values
    missing_website = [r for r in rows if not r.get("website", "").strip()]
    if missing_website:
        typer.echo(
            f"\n  {YELLOW}Warning:{RESET} {len(missing_website)} of {len(rows)} "
            f"contact(s) don't have a company website."
        )
        if not _confirm("Proceed without them?", default=True):
            return None
        # Filter out rows without website
        rows = [r for r in rows if r.get("website", "").strip()]
        if not rows:
            typer.echo(f"  {RED}No contacts left after filtering.{RESET}")
            return None
        typer.echo(f"  Continuing with {len(rows)} contact(s).")

    return rows


def _write_results(rows: list[dict], results: list[dict], output: str, fmt: str) -> None:
    if fmt == "json":
        dest = sys.stdout if output == "-" else open(output, "w", encoding="utf-8")
        json.dump(results, dest, indent=2, ensure_ascii=False)
        dest.write("\n")
        if dest is not sys.stdout:
            dest.close()
    elif fmt == "stdout":
        for r in results:
            name = f"{r['first_name']} {r['last_name']}"
            typer.echo(f"\n{'='*60}")
            typer.echo(f"To: {name} <{r['email']}> @ {r['company']}")
            if r.get("generated_subject"):
                typer.echo(f"Subject: {r['generated_subject']}")
            typer.echo(f"{'='*60}")
            typer.echo(r["generated_email"])
    else:
        fieldnames = list(rows[0].keys()) + ["generated_subject", "generated_email"]
        dest = sys.stdout if output == "-" else open(output, "w", newline="", encoding="utf-8")
        writer = csv.DictWriter(dest, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
        if dest is not sys.stdout:
            dest.close()


# ── run logic (reusable from both CLI and REPL) ─────────────────────────────


def do_run(
    input_csv: str,
    output: str = "output.csv",
    output_format: str = "csv",
    model: str | None = None,
    max_tokens: int | None = None,
    system_prompt: str | None = None,
    prompt_template: str | None = None,
    delay: float = 0.5,
    send: bool = False,
) -> None:
    """Core run logic shared by the CLI command and the REPL."""
    _ensure_config()
    identity = config.get_identity()
    profile = config.get_profile()

    # ── Resolve provider ──
    providers = config.get_providers()
    default_provider_name = config.get_default_provider_name()

    if model:
        detected = generator.detect_provider_for_model(model, providers)
        if detected:
            provider_name = detected
        else:
            # Unknown model prefix — route to a proxy provider
            proxy_providers = {n: p for n, p in providers.items() if p.get("type") == "proxy"}
            if len(proxy_providers) > 1:
                picked = _select_proxy_provider(proxy_providers)
                if not picked:
                    typer.echo(f"  {DIM}Cancelled.{RESET}")
                    return
                provider_name = picked
            elif len(proxy_providers) == 1:
                provider_name = next(iter(proxy_providers))
            else:
                typer.echo(
                    f"  {RED}Error:{RESET} Model '{model}' doesn't match any configured provider.\n"
                    f"  Known prefixes: claude-* → anthropic, gpt-*/o1-*/o3-* → openai.\n"
                    f"  For custom models, add a proxy provider first: provider add"
                )
                return
    else:
        provider_name = default_provider_name

    provider_config = providers.get(provider_name)
    if not provider_config:
        # Fallback: check legacy api_keys
        legacy_key = config.get_api_key("anthropic")
        if legacy_key:
            provider_config = {"type": "anthropic", "api_key": legacy_key, "default_model": generator.DEFAULT_MODEL}
        else:
            typer.echo(f"{RED}Error:{RESET} No provider configured. Run: provider add")
            return

    effective_model = model or provider_config.get("default_model") or generator.DEFAULT_MODEL

    if provider_config.get("type") == "proxy":
        typer.echo(
            f"  {YELLOW}Note:{RESET} Using proxy provider. Output quality depends on the model. "
            f"For best results, use Claude or GPT-4 class models."
        )

    rows = _read_csv(input_csv)

    # Validate email and website columns
    rows = _validate_csv(rows)
    if rows is None:
        return

    use_flags = system_prompt is not None or prompt_template is not None
    campaign = None

    if use_flags:
        sys_prompt = system_prompt or SYSTEM_PROMPT
    else:
        campaign = _select_campaign()
        if campaign is None:
            typer.echo(f"\n  {DIM}Cancelled.{RESET}")
            return
        typer.echo(f"\n  Campaign: {BOLD}{campaign['title']}{RESET}")
        sys_prompt = SYSTEM_PROMPT

    # ── Crawl websites if column present ──
    has_websites = "website" in rows[0]
    website_cache: dict[str, str | None] = {}

    if has_websites:
        urls = list({row["website"] for row in rows if row.get("website", "").strip()})
        if urls:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            typer.echo(f"\n  Crawling {len(urls)} unique website(s)...\n")
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_url = {executor.submit(crawler.crawl_website, url): url for url in urls}
                for future in as_completed(future_to_url):
                    url = future_to_url[future]
                    try:
                        text = future.result()
                    except Exception:
                        text = None
                    website_cache[url] = text
                    if text:
                        typer.echo(f"    {url} ... ok ({len(text)} chars)")
                    else:
                        typer.echo(f"    {url} ... skipped (no content)")

    typer.echo(f"\n  Processing {len(rows)} contacts with '{effective_model}' ({provider_name})...\n")
    results = []
    sender_name = identity.get("name", "")
    batch_size = 5

    def _build_prompt(row, website_text):
        if use_flags and prompt_template:
            return prompt_template.format(**row)
        elif use_flags:
            return (
                f"Write a cold outreach email to {row['first_name']} {row['last_name']} "
                f"at {row['company']}. Their email is {row['email']}."
            )
        elif campaign and _has_enough_context(campaign):
            return build_user_prompt(row, identity, profile, campaign, website_text)
        else:
            return build_template_prompt(row, identity, profile)

    def _generate_one(row):
        website_text = None
        if has_websites:
            website_text = website_cache.get(row.get("website", ""))
        user_prompt = _build_prompt(row, website_text)
        result = generator.generate_with_retry(
            provider_config, sys_prompt, user_prompt, effective_model, max_tokens
        )
        body = result["body"]
        if sender_name:
            body = f"{body}\n\n{sender_name}"
        return {"subject": result["subject"], "body": body}

    # Process in parallel batches
    from concurrent.futures import ThreadPoolExecutor, as_completed

    for batch_start in range(0, len(rows), batch_size):
        batch = rows[batch_start:batch_start + batch_size]
        batch_indices = list(range(batch_start, batch_start + len(batch)))

        # Show what we're processing
        for idx in batch_indices:
            row = rows[idx]
            name = f"{row['first_name']} {row['last_name']}"
            typer.echo(f"  [{idx + 1}/{len(rows)}] {name} ({row['company']})... ", nl=False)
            typer.echo("sending")

        # Run batch in parallel
        batch_results: dict[int, str | Exception] = {}
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            future_to_idx = {
                executor.submit(_generate_one, rows[idx]): idx
                for idx in batch_indices
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    batch_results[idx] = future.result()
                except Exception as e:
                    batch_results[idx] = e

        # Collect results in order
        for idx in batch_indices:
            row = rows[idx]
            name = f"{row['first_name']} {row['last_name']}"
            result = batch_results[idx]
            if isinstance(result, Exception):
                typer.echo(f"  [{idx + 1}/{len(rows)}] {name} ... failed: {result}")
                results.append({**row, "generated_subject": "", "generated_email": f"ERROR: {result}"})
            else:
                typer.echo(f"  [{idx + 1}/{len(rows)}] {name} ... done")
                results.append({**row, "generated_subject": result["subject"], "generated_email": result["body"]})

        # Delay between batches, not between individual requests
        if batch_start + batch_size < len(rows):
            time.sleep(delay)

    _write_results(rows, results, output, output_format)

    success = sum(1 for r in results if not r["generated_email"].startswith("ERROR:"))
    typer.echo(f"\n  Done! {success}/{len(rows)} emails generated.")
    if output_format == "csv" and output != "-":
        typer.echo(f"  Output saved to: {output}")

    # Send via SMTP if --send flag is set
    if send:
        _do_send_results(results)


def _do_send_results(results: list[dict], subject: str = "") -> None:
    """Send generated emails via SMTP.

    Subject priority: --subject flag > per-email generated_subject > prompt user.
    """
    smtp_config = config.get_smtp()
    if not smtp_config:
        typer.echo(f"\n  {YELLOW}SMTP not configured.{RESET} Let's set it up now.\n")
        smtp_setup_cmd()
        smtp_config = config.get_smtp()
        if not smtp_config:
            typer.echo(f"\n  {RED}SMTP setup was cancelled. Cannot send emails.{RESET}")
            return

    # Filter to successful emails only
    sendable = [r for r in results if not r.get("generated_email", "").startswith("ERROR:")]
    if not sendable:
        typer.echo(f"  {YELLOW}No emails to send.{RESET}")
        return

    # Check if we have per-email subjects
    has_per_email_subjects = any(r.get("generated_subject") for r in sendable)

    # Determine subject strategy
    if not subject and not has_per_email_subjects:
        subject = _ask("Email subject line")
        if not subject:
            typer.echo(f"  {RED}Subject is required.{RESET}")
            return

    typer.echo(f"\n  {BOLD}Sending {len(sendable)} emails...{RESET}")
    typer.echo(f"  From: {smtp_config.get('sender_name', '')} <{smtp_config['sender_email']}>")
    if subject:
        typer.echo(f"  Subject: {subject} (all emails)")
    else:
        typer.echo(f"  Subject: {DIM}per-email (AI-generated){RESET}")
    typer.echo()

    if not _confirm(f"Send {len(sendable)} emails?"):
        typer.echo(f"  {DIM}Cancelled.{RESET}")
        return

    sent = 0
    failed = 0
    for r in sendable:
        to_email = r["email"]
        to_name = f"{r.get('first_name', '')} {r.get('last_name', '')}".strip()
        body = r["generated_email"]
        email_subject = subject or r.get("generated_subject", "")
        if not email_subject:
            typer.echo(f"  {RED}✗{RESET} {to_name} <{to_email}> — no subject line")
            failed += 1
            continue
        try:
            sender.send_email(smtp_config, to_email, to_name, email_subject, body)
            typer.echo(f"  {GREEN}✓{RESET} {to_name} <{to_email}> — {DIM}{email_subject}{RESET}")
            sent += 1
        except Exception as e:
            typer.echo(f"  {RED}✗{RESET} {to_name} <{to_email}> — {e}")
            failed += 1

    typer.echo(f"\n  Sent: {sent}, Failed: {failed}")


def do_send(input_csv: str, subject: str = "") -> None:
    """Send emails from a previously generated output CSV."""
    path = Path(input_csv)
    if not path.exists():
        typer.echo(f"  {RED}File not found:{RESET} {input_csv}")
        return

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        typer.echo(f"  {RED}No rows found in {input_csv}{RESET}")
        return

    # Validate required columns
    required = {"email", "generated_email"}
    missing = required - set(rows[0].keys())
    if missing:
        typer.echo(f"  {RED}Missing columns:{RESET} {', '.join(missing)}")
        typer.echo(f"  Expected a CSV with at least: email, first_name, last_name, generated_email")
        return

    _do_send_results(rows, subject)


# ── SMTP setup commands ──────────────────────────────────────────────────────


def smtp_setup_cmd() -> None:
    """Interactive SMTP configuration."""
    typer.echo(f"\n  {BOLD}SMTP Setup{RESET} {DIM}(press ESC to cancel){RESET}\n")

    # Common presets
    typer.echo(f"  {DIM}Common SMTP hosts:{RESET}")
    typer.echo(f"    Gmail:     smtp.gmail.com (port 587, use app password)")
    typer.echo(f"    Outlook:   smtp.office365.com (port 587)")
    typer.echo(f"    Zoho:      smtp.zoho.com (port 587)")
    typer.echo(f"    Custom:    your own SMTP server\n")

    host = _ask("SMTP host", "smtp.gmail.com")
    port_str = _ask("SMTP port", "587")
    port = int(port_str)
    username = _ask("SMTP username (email)")

    # Show app password guidance for Gmail
    if "gmail" in host.lower():
        typer.echo(f"\n  {YELLOW}Gmail requires an App Password (not your regular password).{RESET}")
        typer.echo(f"  {DIM}1. Enable 2-Step Verification on your Google account{RESET}")
        typer.echo(f"  {DIM}2. Go to: https://myaccount.google.com/apppasswords{RESET}")
        typer.echo(f"  {DIM}3. Generate a password for 'Mail' and paste it below{RESET}\n")

    password = _ask("SMTP password (app password for Gmail)", hide=True)
    sender_email = _ask("Sender email", username)

    identity = config.get_identity()
    default_name = identity.get("name", "")
    sender_name = _ask("Sender display name", default_name)

    use_tls = _confirm("Use TLS?", default=True)

    config.set_smtp(host, port, username, password, sender_email, sender_name, use_tls)
    typer.echo(f"\n  {GREEN}SMTP settings saved.{RESET}")

    # Offer to test
    if _confirm("Test connection now?", default=True):
        smtp_test_cmd()


def smtp_test_cmd() -> None:
    """Test the SMTP connection."""
    smtp_config = config.get_smtp()
    if not smtp_config:
        typer.echo(f"  {RED}SMTP not configured.{RESET} Run 'smtp setup' first.")
        return

    typer.echo(f"  Testing connection to {smtp_config['host']}:{smtp_config['port']}...")
    err = sender.test_connection(smtp_config)
    if err:
        typer.echo(f"  {RED}Connection failed:{RESET} {err}")
    else:
        typer.echo(f"  {GREEN}Connection successful!{RESET}")


def smtp_show_cmd() -> None:
    """Show current SMTP configuration."""
    smtp_config = config.get_smtp()
    if not smtp_config:
        typer.echo(f"  {DIM}SMTP not configured. Run 'smtp setup' to set up.{RESET}")
        return
    typer.echo(f"  Host:     {smtp_config['host']}")
    typer.echo(f"  Port:     {smtp_config['port']}")
    typer.echo(f"  Username: {smtp_config['username']}")
    typer.echo(f"  Password: {'*' * 8}")
    typer.echo(f"  From:     {smtp_config.get('sender_name', '')} <{smtp_config['sender_email']}>")
    typer.echo(f"  TLS:      {'yes' if smtp_config.get('use_tls', True) else 'no'}")


# ── typer run command (for direct CLI usage) ─────────────────────────────────


@app.command()
def run(
    input_csv: str = typer.Argument(help="Path to input CSV file"),
    output: str = typer.Option("output.csv", "-o", "--output", help="Output path (use '-' for stdout)"),
    output_format: str = typer.Option("csv", "-f", "--format", help="Output format: csv, json, stdout"),
    model: Optional[str] = typer.Option(None, "--model", help="Model ID (auto-detects provider)"),
    max_tokens: Optional[int] = typer.Option(None, "--max-tokens", help="Override max tokens"),
    system_prompt: Optional[str] = typer.Option(None, "--system-prompt", help="Custom system prompt"),
    prompt_template: Optional[str] = typer.Option(None, "--template", help="Custom prompt template"),
    delay: float = typer.Option(0.5, "--delay"),
    send: bool = typer.Option(False, "--send", help="Send emails via SMTP after generating"),
) -> None:
    """Generate personalized cold outreach emails from a CSV."""
    do_run(input_csv, output, output_format, model, max_tokens, system_prompt, prompt_template, delay, send)


# ── REPL shell ───────────────────────────────────────────────────────────────

SHELL_HELP = f"""\
{BOLD}Available commands:{RESET}

  {GREEN}run{RESET} <file.csv> [options]     Generate emails from a CSV
      -o, --output <path>         Output path (default: output.csv)
      -f, --format <csv|json|stdout>
      --max-tokens <number>
      --model <model-id>
      --system-prompt <text>      Custom system prompt
      --template <text>           Custom prompt template
      --delay <seconds>
      --send                      Send emails via SMTP after generating

  {GREEN}send{RESET} <output.csv>             Send emails from a previously generated CSV
      --subject <text>            Email subject line

  {GREEN}smtp setup{RESET}                   Configure SMTP settings
  {GREEN}smtp test{RESET}                    Test SMTP connection
  {GREEN}smtp show{RESET}                    Show current SMTP config

  {GREEN}config{RESET}                        Show current configuration
  {GREEN}config init{RESET}                  Set up API key & profile info
  {GREEN}config set-key{RESET} [provider]    Set an API key

  {GREEN}profile list{RESET}                 List all profiles
  {GREEN}profile create{RESET} <name>        Create a new profile
  {GREEN}profile use{RESET} <name>           Switch to a profile
  {GREEN}profile delete{RESET} <name>        Delete a profile

  {GREEN}provider list{RESET}                Show configured providers & default
  {GREEN}provider add{RESET}                 Add a new provider (Anthropic/OpenAI/Proxy)
  {GREEN}provider delete{RESET} <name>       Delete a provider
  {GREEN}provider default{RESET} <name>      Set default provider for runs

  {GREEN}help{RESET}                         Show this help
  {GREEN}exit{RESET} / {GREEN}q{RESET}                    Exit the shell

  {DIM}Press ESC during any prompt to cancel.{RESET}
"""


def _parse_run_args(tokens: list[str]) -> dict:
    """Parse run subcommand arguments from REPL tokens."""
    args: dict = {
        "output": "output.csv",
        "output_format": "csv",
        "model": None,
        "max_tokens": None,
        "system_prompt": None,
        "prompt_template": None,
        "delay": 0.5,
        "send": False,
    }
    positional = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-o", "--output") and i + 1 < len(tokens):
            args["output"] = tokens[i + 1]; i += 2
        elif tok in ("-f", "--format") and i + 1 < len(tokens):
            args["output_format"] = tokens[i + 1]; i += 2
        elif tok == "--model" and i + 1 < len(tokens):
            args["model"] = tokens[i + 1]; i += 2
        elif tok == "--max-tokens" and i + 1 < len(tokens):
            args["max_tokens"] = int(tokens[i + 1]); i += 2
        elif tok == "--system-prompt" and i + 1 < len(tokens):
            args["system_prompt"] = tokens[i + 1]; i += 2
        elif tok == "--template" and i + 1 < len(tokens):
            args["prompt_template"] = tokens[i + 1]; i += 2
        elif tok == "--delay" and i + 1 < len(tokens):
            args["delay"] = float(tokens[i + 1]); i += 2
        elif tok == "--send":
            args["send"] = True; i += 1
        else:
            positional.append(tok); i += 1

    if not positional:
        return {}
    args["input_csv"] = positional[0]
    return args


def _parse_send_args(tokens: list[str]) -> dict:
    """Parse send subcommand arguments from REPL tokens."""
    args: dict = {"subject": ""}
    positional = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--subject" and i + 1 < len(tokens):
            args["subject"] = tokens[i + 1]; i += 2
        else:
            positional.append(tok); i += 1
    if not positional:
        return {}
    args["input_csv"] = positional[0]
    return args


def _run_shell() -> None:
    """Interactive REPL shell."""
    _ensure_config()

    profile_name = config.get_active_profile_name()
    identity = config.get_identity()
    display_name = identity.get("name") or profile_name
    pc = _profile_color()

    typer.echo(f"\n{BOLD}OpenCold{RESET} interactive shell")
    typer.echo(f"Logged in as {pc}\u25cf {display_name}{RESET} (profile: {pc}{profile_name}{RESET})")
    typer.echo(f"Type {GREEN}help{RESET} for commands, {GREEN}exit{RESET} to quit.\n")

    session = PromptSession(history=InMemoryHistory(), completer=_ReplCompleter())

    while True:
        try:
            line = session.prompt(ANSI(_prompt_str()), rprompt=ANSI(_rprompt_str())).strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo("\nBye!")
            break

        if not line:
            continue

        try:
            tokens = shlex.split(line)
        except ValueError as e:
            typer.echo(f"Parse error: {e}")
            continue

        cmd = tokens[0].lower()
        rest = tokens[1:]

        try:
            if cmd in ("exit", "q"):
                typer.echo("Bye!")
                break

            elif cmd == "help":
                typer.echo(SHELL_HELP)

            elif cmd == "run":
                args = _parse_run_args(rest)
                if not args:
                    # No file specified — show interactive selector
                    csv_file = _select_csv_file()
                    if csv_file:
                        do_run(input_csv=csv_file)
                else:
                    do_run(**args)

            elif cmd == "config":
                sub = rest[0] if rest else None
                if sub is None:
                    config_show(None)
                elif sub == "init":
                    config_init()
                elif sub == "set-key":
                    provider = rest[1] if len(rest) > 1 else "anthropic"
                    key = _ask(f"API key for '{provider}'", hide=True)
                    config.set_api_key(provider, key)
                    typer.echo(f"  API key for '{provider}' saved.")
                else:
                    typer.echo(f"Unknown config command: {sub}")

            elif cmd == "profile":
                sub = rest[0] if rest else "list"
                if sub == "list":
                    profile_list()
                elif sub == "create":
                    if len(rest) < 2:
                        typer.echo("Usage: profile create <name>")
                    else:
                        profile_create(rest[1])
                elif sub == "use":
                    if len(rest) < 2:
                        typer.echo("Usage: profile use <name>")
                    else:
                        profile_use(rest[1])
                elif sub == "delete":
                    if len(rest) < 2:
                        typer.echo("Usage: profile delete <name>")
                    else:
                        profile_delete(rest[1])
                else:
                    typer.echo(f"Unknown profile command: {sub}")

            elif cmd == "provider":
                sub = rest[0] if rest else "list"
                if sub == "list":
                    provider_list_cmd()
                elif sub == "add":
                    provider_add_cmd()
                elif sub == "delete":
                    if len(rest) < 2:
                        typer.echo("Usage: provider delete <name>")
                    else:
                        provider_delete_cmd(rest[1])
                elif sub == "default":
                    if len(rest) < 2:
                        typer.echo("Usage: provider default <name>")
                    else:
                        provider_default_cmd(rest[1])
                else:
                    typer.echo(f"Unknown provider command: {sub}")

            elif cmd == "send":
                args = _parse_send_args(rest)
                if not args:
                    typer.echo("Usage: send <output.csv> [--subject <text>]")
                else:
                    do_send(**args)

            elif cmd == "smtp":
                sub = rest[0] if rest else "show"
                if sub == "setup":
                    smtp_setup_cmd()
                elif sub == "test":
                    smtp_test_cmd()
                elif sub == "show":
                    smtp_show_cmd()
                else:
                    typer.echo(f"Unknown smtp command: {sub}")

            else:
                typer.echo(f"Unknown command: {cmd}. Type 'help' for available commands.")

        except Cancelled:
            typer.echo(f"\n  {DIM}Cancelled.{RESET}")
        except typer.Exit:
            pass
        except Exception as e:
            typer.echo(f"{RED}Error:{RESET} {e}")


# ── entrypoint ───────────────────────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    """OpenCold — cold outreach email generator powered by Claude."""
    if ctx.invoked_subcommand is None:
        _run_shell()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
