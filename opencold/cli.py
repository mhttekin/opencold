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

from opencold import config, crawler, discovery, enricher, generator, quality, sender, verifier
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
smtp_app = typer.Typer(help="Manage SMTP sending configuration.")
app.add_typer(smtp_app, name="smtp")


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
    if not sys.stdin.isatty():
        return default
    yn = "Y/n" if default else "y/N"
    try:
        result = PromptSession(key_bindings=_kb).prompt(f"  {text} [{yn}]: ")
        if not result.strip():
            return default
        return result.strip().lower() in ("y", "yes")
    except (KeyboardInterrupt, EOFError, OSError):
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
        lines.append(("bold", "  Select proxy provider  "))
        lines.append(("fg:ansibrightblack", "(↑↓ move, Enter select, Esc cancel)\n\n"))
        for i, name in enumerate(names):
            prov = proxy_providers[name]
            base = prov.get("base_url", "")
            if i == selected[0]:
                lines.append(("fg:cyan bold", f"  ▸ {name}"))
                if base:
                    lines.append(("fg:ansibrightblack", f" ({base})"))
                lines.append(("", "\n"))
            else:
                lines.append(("", f"    {name}"))
                if base:
                    lines.append(("fg:ansibrightblack", f" ({base})"))
                lines.append(("", "\n"))
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

    _TOP_COMMANDS = ["discover", "run", "prepare", "draft", "review", "send", "verify", "smtp", "config", "profile", "provider", "help", "exit", "q"]
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

        # After "run"/"draft", complete file paths and --flags
        if first in ("run", "draft"):
            current_word = words[-1] if not text.endswith(" ") else ""
            # Suggest --flags when user starts typing with -
            if current_word.startswith("-"):
                run_flags = [
                    "--model", "--max-tokens", "--output", "--format",
                    "--system-prompt", "--template", "--delay", "--workers", "--send",
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

        # After "discover", complete source files and --flags
        if first == "discover":
            current_word = words[-1] if not text.endswith(" ") else ""
            if current_word.startswith("-"):
                for flag in ["--icp", "--region", "--mode", "--output", "--limit", "--source-limit", "--require-contact", "--guess-role-email", "--find-people", "--count", "--max-pages", "--workers"]:
                    if flag.startswith(current_word) and flag != current_word:
                        yield Completion(flag, start_position=-len(current_word))
                return
            prefix_len = len(words[0]) + 1
            from prompt_toolkit.document import Document
            sub_text = text[prefix_len:] if len(text) > prefix_len else ""
            sub_doc = Document(sub_text)
            yield from self._path_completer.get_completions(sub_doc, complete_event)

        # After "prepare", complete file paths and --flags
        if first == "prepare":
            current_word = words[-1] if not text.endswith(" ") else ""
            if current_word.startswith("-"):
                for flag in ["--output", "--max-pages", "--workers"]:
                    if flag.startswith(current_word) and flag != current_word:
                        yield Completion(flag, start_position=-len(current_word))
                return
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

        # After "verify"/"review", complete file paths
        if first in ("verify", "review"):
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
    ("Serper (for discovery)", "serper", ""),
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
        ptype = prov.get("type", "")
        is_default = name == default
        marker = f"  {CYAN}\u2190 default{RESET}" if is_default else ""
        check = f"{GREEN}\u2713{RESET}" if is_default else "\u25cf"
        base_url = prov.get("base_url", "")
        url_info = f"  {DIM}{base_url}{RESET}" if base_url else ""
        if ptype == "serper":
            typer.echo(f"  {check} {BOLD}{name}{RESET}  {DIM}{masked}{RESET}  {DIM}(discovery search){RESET}")
        else:
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

        # Serper is a search API, not an LLM — skip model/tokens
        if ptype == "serper":
            config.add_provider("serper", ptype, api_key)
            typer.echo(f"\n  {GREEN}\u2713{RESET} serper added. Discovery will now use Google search.")
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


def _display_name(row: dict) -> str:
    """A row's recipient name — 'name' column, or legacy first/last combined."""
    name = (row.get("name") or "").strip()
    if name:
        return name
    first = (row.get("first_name") or "").strip()
    last = (row.get("last_name") or "").strip()
    return f"{first} {last}".strip()


def _normalize_name_columns(rows: list[dict]) -> list[dict]:
    """Ensure every row has a 'name' key (combining legacy first/last if needed)."""
    for row in rows:
        if not (row.get("name") or "").strip():
            combined = _display_name(row)
            if combined:
                row["name"] = combined
    return rows


def _read_csv(path: str, require_email: bool = True) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        typer.echo(f"Error: file '{path}' not found.", err=True)
        raise typer.Exit(1)
    if not rows:
        typer.echo("Error: CSV is empty.", err=True)
        raise typer.Exit(1)
    columns = set(rows[0].keys())

    def _is_wall_row(r: dict) -> bool:
        # Discovery's visual-wall rows: a banner (company starts with ═) or a
        # fully blank gap row. Drop them so a company CSV feeds straight into run.
        if (r.get("company") or "").lstrip().startswith("═"):
            return True
        return not any((v or "").strip() for v in r.values())

    rows = [r for r in rows if not _is_wall_row(r)]
    if not rows:
        typer.echo("Error: CSV has no usable rows.", err=True)
        raise typer.Exit(1)
    # Accept a single 'name' column (preferred) or legacy first_name/last_name.
    if "name" not in columns and "first_name" not in columns:
        typer.echo("Error: CSV missing a 'name' column.", err=True)
        raise typer.Exit(1)
    required = {"company"}
    if require_email:
        required.add("email")
    missing = required - columns
    if missing:
        typer.echo(f"Error: CSV missing columns: {', '.join(missing)}", err=True)
        raise typer.Exit(1)
    return _normalize_name_columns(rows)


def _validate_csv(rows: list[dict], allow_missing_email: bool = False) -> list[dict] | None:
    """Validate CSV rows for email and website. Returns filtered rows or None to abort."""
    # Check email column — must have at least one valid email
    missing_email = [r for r in rows if not r.get("email", "").strip()]
    if missing_email and not allow_missing_email:
        typer.echo(
            f"\n  {RED}Error:{RESET} {len(missing_email)} row(s) have no email address. "
            f"Cannot proceed without email addresses."
        )
        return None
    if missing_email and allow_missing_email:
        typer.echo(
            f"\n  {YELLOW}Warning:{RESET} {len(missing_email)} row(s) have no email address. "
            f"They can be enriched and reviewed, but cannot be drafted or sent yet."
        )

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


def _is_enriched(rows: list[dict]) -> bool:
    return bool(rows and "personalization_facts" in rows[0])


def _clamp_workers(workers: int) -> int:
    """Keep parallelism useful without hammering websites or LLM APIs."""
    return max(1, min(int(workers or 1), 8))


def _resolve_missing_websites(rows: list[dict], workers: int = 8) -> list[dict]:
    """Fill in missing 'website' values by searching for the company name.

    Uses discovery.resolve_company_website (ddgs → Brave → Serper → DDG HTML),
    so it works with zero configuration and free backends. Rows that already
    have a website are left untouched. Companies are de-duplicated so each name
    is searched only once. Returns the same rows with 'website' populated where
    a confident match was found.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    has_col = bool(rows) and "website" in rows[0]
    targets = [
        r for r in rows
        if r.get("company", "").strip()
        and not (r.get("website", "").strip() if has_col else "")
    ]
    if not targets:
        return rows

    # Ensure every row carries a 'website' key so the column stays consistent
    # for validation and CSV output downstream.
    for r in rows:
        r.setdefault("website", "")

    by_company: dict[str, list[dict]] = {}
    for r in targets:
        by_company.setdefault(r["company"].strip(), []).append(r)

    workers = _clamp_workers(workers)
    worker_count = max(1, min(workers, len(by_company)))
    typer.echo(
        f"\n  {len(targets)} row(s) missing a website — searching by company name "
        f"with {worker_count} worker(s)..."
    )

    resolved: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_company = {
            executor.submit(discovery.resolve_company_website, company): company
            for company in by_company
        }
        for future in as_completed(future_to_company):
            company = future_to_company[future]
            try:
                url = future.result()
            except Exception:
                url = None
            if url:
                resolved[company] = url

    found = 0
    for company, company_rows in by_company.items():
        url = resolved.get(company)
        if url:
            found += 1
            for r in company_rows:
                r["website"] = url
            typer.echo(f"    {GREEN}✓{RESET} {company} → {url}")
        else:
            typer.echo(f"    {YELLOW}✗{RESET} {company} {DIM}— no website found{RESET}")

    plural = "y" if len(by_company) == 1 else "ies"
    typer.echo(f"  Resolved {found}/{len(by_company)} compan{plural} from name.")
    return rows


def _enrich_rows(rows: list[dict], max_pages: int = 4, workers: int = 8) -> list[dict]:
    """Enrich rows with verification, website status, and grounded facts."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    workers = _clamp_workers(workers)

    websites = []
    seen_websites = set()
    for row in rows:
        website = enricher.normalize_url(row.get("website", ""))
        if website and website not in seen_websites:
            seen_websites.add(website)
            websites.append(website)

    website_results: dict[str, dict] = {}
    if websites:
        worker_count = max(1, min(workers, len(websites)))
        typer.echo(f"  Crawling {len(websites)} unique website(s) with {worker_count} worker(s)...")
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_website = {
                executor.submit(enricher.enrich_website, website, max_pages): website
                for website in websites
            }
            for future in as_completed(future_to_website):
                website = future_to_website[future]
                try:
                    website_results[website] = future.result()
                except Exception as e:
                    website_results[website] = {
                        "website_status": "fetch_failed",
                        "company_summary": "",
                        "personalization_facts": "",
                        "source_urls": "",
                        "personalization_score": "0",
                        "quality_warnings": f"website_fetch_failed{enricher.FACT_SEPARATOR}{type(e).__name__}",
                        "enrichment_json": "{}",
                    }
                score = website_results[website].get("personalization_score", "0")
                status = website_results[website].get("website_status", "")
                typer.echo(f"    {website} ... {status}, score {score}")

    enriched = []
    for idx, row in enumerate(rows, start=1):
        name = _display_name(row)
        label = name or row.get("company", "") or row.get("email", "")
        typer.echo(f"  [{idx}/{len(rows)}] {label}... ", nl=False)
        enriched_row = dict(row)
        email = row.get("email", "")
        if email.strip():
            email_result = verifier.verify_email(email)
            enriched_row["verification_status"] = "valid" if email_result["valid"] else f"invalid: {email_result['reason']}"
        else:
            enriched_row["verification_status"] = "missing"
        website = enricher.normalize_url(row.get("website", ""))
        enriched_row.update(
            website_results.get(website) or enricher.enrich_website("", max_pages=max_pages)
        )
        score = enriched_row.get("personalization_score", "0")
        status = enriched_row.get("website_status", "")
        typer.echo(f"{status}, score {score}")
        enriched.append(enriched_row)
    return enriched


def _write_results(rows: list[dict], results: list[dict], output: str, fmt: str) -> None:
    if fmt == "json":
        dest = sys.stdout if output == "-" else open(output, "w", encoding="utf-8")
        json.dump(results, dest, indent=2, ensure_ascii=False)
        dest.write("\n")
        if dest is not sys.stdout:
            dest.close()
    elif fmt == "stdout":
        for r in results:
            name = _display_name(r)
            typer.echo(f"\n{'='*60}")
            typer.echo(f"To: {name} <{r['email']}> @ {r['company']}")
            if r.get("generated_subject"):
                typer.echo(f"Subject: {r['generated_subject']}")
            typer.echo(f"{'='*60}")
            typer.echo(r["generated_email"])
    else:
        fieldnames = list(rows[0].keys())
        for key in ("quality_warnings", "generated_subject", "generated_email"):
            if key not in fieldnames:
                fieldnames.append(key)
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
    require_enriched: bool = False,
    workers: int = 5,
) -> None:
    """Core run logic shared by the CLI command and the REPL."""
    _ensure_config()

    # ── Check enrichment early (before provider resolution) ──
    rows = _read_csv(input_csv)
    # Fill in any missing company websites from their names (free web search)
    # before validation so name-only leads aren't dropped.
    if not _is_enriched(rows):
        rows = _resolve_missing_websites(rows, workers=workers)
    rows = _validate_csv(rows)
    if rows is None:
        return

    if require_enriched and not _is_enriched(rows):
        typer.echo(
            f"\n  {RED}Error:{RESET} draft expects a prepared CSV with "
            f"'personalization_facts'. Run: prepare {input_csv} -o enriched.csv"
        )
        return

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
    workers = _clamp_workers(workers)

    if provider_config.get("type") == "proxy":
        typer.echo(
            f"  {YELLOW}Note:{RESET} Using proxy provider. Output quality depends on the model. "
            f"For best results, use Claude or GPT-4 class models."
        )

    # ── Verify email addresses (format + MX) ──
    typer.echo(f"\n  Verifying {len(rows)} email(s)...")
    domains_seen: set[str] = set()
    invalid = []
    for row in rows:
        result = verifier.verify_email(row["email"])
        domain = row["email"].split("@")[-1] if "@" in row["email"] else ""
        if domain and domain not in domains_seen:
            domains_seen.add(domain)
        if not result["valid"]:
            invalid.append((row, result["reason"]))

    if invalid:
        typer.echo(f"  {RED}{len(invalid)} invalid email(s):{RESET}")
        for row, reason in invalid:
            name = _display_name(row)
            typer.echo(f"    {RED}✗{RESET} {row['email']} — {reason}")
        valid_rows = [r for r in rows if r not in [inv[0] for inv in invalid]]
        if not valid_rows:
            typer.echo(f"\n  {RED}No valid emails remaining.{RESET}")
            return
        if not _confirm(f"Continue with {len(valid_rows)}/{len(rows)} valid emails?", default=True):
            return
        rows = valid_rows
    else:
        typer.echo(f"  {GREEN}All {len(rows)} email(s) verified{RESET} ({len(domains_seen)} domain(s) checked)")

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

    # ── Enrich websites if this is a raw leads file ──
    has_websites = "website" in rows[0]
    if has_websites and not _is_enriched(rows):
        typer.echo(f"\n  Preparing enriched facts from company websites...\n")
        rows = _enrich_rows(rows, workers=workers)
    elif _is_enriched(rows):
        typer.echo(f"\n  Using prepared facts from input CSV; skipping website enrichment.")

    typer.echo(f"\n  Processing {len(rows)} contacts with '{effective_model}' ({provider_name})...\n")
    results = []
    sender_name = identity.get("name", "")
    batch_size = workers

    def _build_prompt(row, website_text):
        if use_flags and prompt_template:
            return prompt_template.format(**row)
        elif use_flags:
            return (
                f"Write a cold outreach email to {_display_name(row)} "
                f"at {row['company']}. Their email is {row['email']}."
            )
        elif campaign and _has_enough_context(campaign):
            return build_user_prompt(
                row,
                identity,
                profile,
                campaign,
                website_text,
                personalization_facts=row.get("personalization_facts", ""),
            )
        else:
            return build_template_prompt(row, identity, profile)

    def _generate_one(row):
        website_text = None
        if has_websites and not row.get("personalization_facts"):
            website_text = crawler.crawl_website(row.get("website", ""))
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
            name = _display_name(row)
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
            name = _display_name(row)
            result = batch_results[idx]
            if isinstance(result, Exception):
                typer.echo(f"  [{idx + 1}/{len(rows)}] {name} ... failed: {result}")
                warnings = quality.merge_warnings(row.get("quality_warnings", ""), ["generation_failed"])
                results.append({**row, "quality_warnings": warnings, "generated_subject": "", "generated_email": f"ERROR: {result}"})
            else:
                typer.echo(f"  [{idx + 1}/{len(rows)}] {name} ... done")
                draft_warnings = quality.evaluate_draft(
                    result["subject"],
                    result["body"],
                    row.get("personalization_facts", ""),
                )
                warnings = quality.merge_warnings(row.get("quality_warnings", ""), draft_warnings)
                results.append({
                    **row,
                    "quality_warnings": warnings,
                    "generated_subject": result["subject"],
                    "generated_email": result["body"],
                })

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
        to_name = _display_name(r)
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
        typer.echo(f"  Expected a CSV with at least: email, name, generated_email")
        return

    _do_send_results(rows, subject)


def do_prepare(input_csv: str, output: str = "enriched.csv", max_pages: int = 4, workers: int = 8) -> None:
    """Prepare an enriched lead CSV without generating emails."""
    rows = _read_csv(input_csv, require_email=False)
    # Fill in any missing company websites from their names (free web search).
    rows = _resolve_missing_websites(rows, workers=workers)
    rows = _validate_csv(rows, allow_missing_email=True)
    if rows is None:
        return

    typer.echo(f"\n  Enriching {len(rows)} lead(s)...\n")
    enriched_rows = _enrich_rows(rows, max_pages=max_pages, workers=workers)
    enricher.write_csv(enriched_rows, output)
    typer.echo(f"\n  Enriched leads saved to: {output}")


def _print_discover_progress(processed: int, total: int, found: int, elapsed: float) -> None:
    """Single-line discovery progress to stderr (shared by both modes)."""
    if processed == 0:
        eta_str = "calculating..."
    else:
        avg = elapsed / processed
        eta = int(avg * max(total - processed, 0))
        eta_str = f"~{eta}s left" if eta < 60 else f"~{eta // 60}m {eta % 60}s left"
    sys.stderr.write(
        f"\r  Processing {processed}/{total} companies "
        f"| {found} found | {int(elapsed)}s elapsed | {eta_str}   "
    )
    sys.stderr.flush()


def do_discover(
    sources_file: str = "",
    icp: str = "",
    output: str = "leads.csv",
    limit: int = 10,
    require_contact: bool = False,
    max_pages: int = 3,
    workers: int = 8,
    source_limit: int = 25,
    guess_role_email: bool = False,
    region: str = "",
    mode: str = "companies",
    find_people: bool = False,
    seed_count: int = 30,
) -> None:
    """Discover leads (experimental — review before outreach).

    Default 'companies' mode: given --icp and --region, finds a ranked company
    list with a durable contact bundle (company email, phone, address, company
    LinkedIn). Legacy 'people' mode finds a named contact per company from a
    sources file (results can be stale).
    """
    if mode == "people":
        _do_discover_people(
            sources_file, icp, output, limit, require_contact,
            max_pages, workers, source_limit, guess_role_email,
        )
        return
    _do_discover_companies(
        icp, region, output, limit, max_pages, workers,
        sources_file, find_people, seed_count, require_contact,
    )


def _do_discover_people(
    sources_file: str,
    icp: str,
    output: str,
    limit: int,
    require_contact: bool,
    max_pages: int,
    workers: int,
    source_limit: int,
    guess_role_email: bool,
) -> None:
    """Legacy person-per-company discovery from a sources file."""
    sources = discovery.load_sources(sources_file or "sources.txt")
    if not sources:
        typer.echo(f"  {RED}No source URLs found in {sources_file or 'sources.txt'}.{RESET}")
        return

    typer.echo(f"\n  {YELLOW}[experimental]{RESET} People discovery (legacy) — results may vary")
    typer.echo(f"  {YELLOW}⚠ Person→company data can be stale; verify before outreach.{RESET}")
    try:
        from ddgs import DDGS
        typer.echo(f"  {GREEN}✓{RESET} Searching with DuckDuckGo")
    except ImportError:
        typer.echo(f"  {YELLOW}⚠{RESET} ddgs package not installed. Run: {BOLD}pip install ddgs{RESET}")
    if discovery._get_serper_key():
        typer.echo(f"  {GREEN}✓{RESET} Serper search API configured (fallback)")

    typer.echo(f"\n  Discovering leads from {len(sources)} source(s)...\n")
    rows = discovery.discover_rows(
        sources,
        icp=icp,
        limit=limit,
        require_contact=require_contact,
        max_pages=max_pages,
        workers=workers,
        source_limit=source_limit,
        guess_role_email=guess_role_email,
        progress_callback=_print_discover_progress,
    )
    sys.stderr.write("\r" + " " * 80 + "\r")
    sys.stderr.flush()
    discovery.write_csv(rows, output)

    with_contact = sum(1 for row in rows if row.get("email"))
    linkedin_count = sum(1 for row in rows if row.get("contact_type") == "linkedin_profile")
    typer.echo(f"  Found {len(rows)} compan{'y' if len(rows) == 1 else 'ies'} ({with_contact} with contact info).")
    if linkedin_count:
        typer.echo(f"  {CYAN}ℹ{RESET} {linkedin_count} contact(s) via LinkedIn search")
    typer.echo(f"  Output saved to: {output}")


def _do_discover_companies(
    icp: str,
    region: str,
    output: str,
    limit: int,
    max_pages: int,
    workers: int,
    sources_file: str,
    find_people: bool,
    seed_count: int,
    require_contact: bool,
) -> None:
    """Company-first discovery: ICP + region -> ranked companies + contact bundle."""
    typer.echo(f"\n  {YELLOW}[experimental]{RESET} Company discovery — review before outreach")
    if not icp or not region:
        typer.echo(f"  {RED}Error:{RESET} companies mode needs --icp and --region.")
        typer.echo(f'  e.g. discover --icp "insurance companies" --region "Bangladesh"')
        return

    try:
        from ddgs import DDGS
        typer.echo(f"  {GREEN}✓{RESET} Searching with DuckDuckGo")
    except ImportError:
        typer.echo(f"  {YELLOW}⚠{RESET} ddgs package not installed. Run: {BOLD}pip install ddgs{RESET}")
    if discovery._get_serper_key():
        typer.echo(f"  {GREEN}✓{RESET} Serper search API configured (fallback)")
    if discovery._resolve_llm_provider():
        typer.echo(f"  {GREEN}✓{RESET} LLM company seeding enabled")
    else:
        typer.echo(f"  {CYAN}ℹ{RESET} No LLM provider — using search-only discovery")
    if find_people:
        typer.echo(f"  {YELLOW}⚠ Person→company data can be stale; verify before outreach.{RESET}")

    sources = (discovery.load_sources(sources_file) or None) if sources_file else None
    typer.echo(f"\n  Discovering '{icp}' companies in '{region}'...\n")
    rows = discovery.discover_company_rows(
        icp=icp,
        region=region,
        sources=sources,
        limit=limit,
        workers=workers,
        max_pages=max_pages,
        use_llm=True,
        seed_count=seed_count,
        find_people=find_people,
        progress_callback=_print_discover_progress,
    )
    sys.stderr.write("\r" + " " * 80 + "\r")
    sys.stderr.flush()

    if require_contact:
        rows = [r for r in rows if r.get("email")]

    discovery.write_company_csv(rows, output)
    with_email = sum(1 for r in rows if r.get("email"))
    with_phone = sum(1 for r in rows if r.get("phone"))
    with_li = sum(1 for r in rows if r.get("linkedin_company_url"))
    typer.echo(
        f"  Found {len(rows)} compan{'y' if len(rows) == 1 else 'ies'} "
        f"({with_email} email, {with_phone} phone, {with_li} LinkedIn)."
    )
    typer.echo(f"  Output saved to: {output}")


def do_review(input_csv: str) -> None:
    """Review enrichment and generation warnings in a CSV file."""
    path = Path(input_csv)
    if not path.exists():
        typer.echo(f"  {RED}File not found:{RESET} {input_csv}")
        return

    rows = enricher.read_csv(input_csv)
    if not rows:
        typer.echo(f"  {RED}No rows found in {input_csv}{RESET}")
        return

    typer.echo(f"\n  Reviewing {len(rows)} row(s)...\n")
    issue_count = 0
    for row in rows:
        warnings = row.get("quality_warnings", "")
        generated = row.get("generated_email", "")
        score = row.get("personalization_score", "")
        if generated and generated.startswith("ERROR:"):
            warnings = f"{warnings}{enricher.FACT_SEPARATOR if warnings else ''}generation_failed"
        if warnings:
            issue_count += 1
            label = _display_name(row)
            label = label or row.get("email", "")
            typer.echo(f"  {YELLOW}!{RESET} {label}  score={score or 'n/a'}  {warnings}")
    if issue_count == 0:
        typer.echo(f"  {GREEN}No quality warnings found.{RESET}")
    else:
        typer.echo(f"\n  Rows with warnings: {issue_count}/{len(rows)}")


def do_verify(input_csv: str) -> None:
    """Verify email addresses in a CSV file."""
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

    if "email" not in rows[0]:
        typer.echo(f"  {RED}Missing 'email' column{RESET}")
        return

    typer.echo(f"\n  Verifying {len(rows)} email(s)...\n")

    valid_count = 0
    invalid_count = 0
    for row in rows:
        email = row["email"].strip()
        result = verifier.verify_email(email)
        name = _display_name(row)
        label = f"{name} <{email}>" if name else email
        if result["valid"]:
            typer.echo(f"  {GREEN}✓{RESET} {label}")
            valid_count += 1
        else:
            typer.echo(f"  {RED}✗{RESET} {label} — {result['reason']}")
            invalid_count += 1

    typer.echo(f"\n  Valid: {valid_count}, Invalid: {invalid_count}")


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


@app.command("send")
def send_cmd(
    input_csv: str = typer.Argument(help="Path to generated output CSV"),
    subject: str = typer.Option("", "--subject", help="Override subject for all emails"),
) -> None:
    """Send emails from a previously generated CSV."""
    do_send(input_csv, subject)


@app.command("verify")
def verify_cmd(
    input_csv: str = typer.Argument(help="Path to input CSV file"),
) -> None:
    """Verify email addresses in a CSV."""
    do_verify(input_csv)


@smtp_app.command("setup")
def smtp_setup_direct() -> None:
    """Configure SMTP settings."""
    smtp_setup_cmd()


@smtp_app.command("test")
def smtp_test_direct() -> None:
    """Test SMTP connection."""
    smtp_test_cmd()


@smtp_app.command("show")
def smtp_show_direct() -> None:
    """Show current SMTP config."""
    smtp_show_cmd()


# ── typer run command (for direct CLI usage) ─────────────────────────────────


@app.command()
def discover(
    sources_file: str = typer.Argument("", help="Optional source URLs file (people mode, or extra channel in companies mode)"),
    icp: str = typer.Option("", "--icp", help="Ideal customer profile / what the target companies do"),
    region: str = typer.Option("", "--region", help="Country or region to target (companies mode)"),
    mode: str = typer.Option("companies", "--mode", help="'companies' (ICP+region) or 'people' (legacy sources)"),
    output: str = typer.Option("leads.csv", "-o", "--output", help="Output discovered lead CSV path"),
    limit: int = typer.Option(10, "--limit", help="Maximum companies to discover"),
    source_limit: int = typer.Option(25, "--source-limit", help="[people] Max candidates per source page"),
    require_contact: bool = typer.Option(False, "--require-contact", help="Only keep companies with an email"),
    guess_role_email: bool = typer.Option(False, "--guess-role-email", help="[people] Low-confidence hello@domain guesses"),
    find_people: bool = typer.Option(False, "--find-people", help="Also search a named contact per company (may be stale)"),
    count: int = typer.Option(30, "--count", help="[companies] Max companies for LLM seeding"),
    max_pages: int = typer.Option(3, "--max-pages", help="Company pages to crawl for facts/contacts"),
    workers: int = typer.Option(8, "--workers", help="Parallel company crawl workers (max 8)"),
) -> None:
    """[Experimental] Discover companies (ICP + region) with a contact bundle, or people (legacy)."""
    do_discover(
        sources_file, icp, output, limit, require_contact, max_pages, workers,
        source_limit, guess_role_email,
        region=region, mode=mode, find_people=find_people, seed_count=count,
    )


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
    workers: int = typer.Option(5, "--workers", help="Parallel crawl/LLM workers (max 8)"),
    send: bool = typer.Option(False, "--send", help="Send emails via SMTP after generating"),
) -> None:
    """Raw CSV: prepare + draft. Prepared CSV: draft again. Sends only with --send."""
    do_run(input_csv, output, output_format, model, max_tokens, system_prompt, prompt_template, delay, send, workers=workers)


@app.command()
def prepare(
    input_csv: str = typer.Argument(help="Path to input CSV file"),
    output: str = typer.Option("enriched.csv", "-o", "--output", help="Output enriched CSV path"),
    max_pages: int = typer.Option(4, "--max-pages", help="Maximum pages to crawl per website"),
    workers: int = typer.Option(8, "--workers", help="Parallel website crawl workers"),
) -> None:
    """Verify and enrich leads without generating emails."""
    do_prepare(input_csv, output, max_pages, workers)


@app.command()
def draft(
    input_csv: str = typer.Argument(help="Path to prepared/enriched CSV file"),
    output: str = typer.Option("drafts.csv", "-o", "--output", help="Output draft CSV path"),
    output_format: str = typer.Option("csv", "-f", "--format", help="Output format: csv, json, stdout"),
    model: Optional[str] = typer.Option(None, "--model", help="Model ID (auto-detects provider)"),
    max_tokens: Optional[int] = typer.Option(None, "--max-tokens", help="Override max tokens"),
    system_prompt: Optional[str] = typer.Option(None, "--system-prompt", help="Custom system prompt"),
    prompt_template: Optional[str] = typer.Option(None, "--template", help="Custom prompt template"),
    delay: float = typer.Option(0.5, "--delay"),
    workers: int = typer.Option(5, "--workers", help="Parallel LLM workers (max 8)"),
) -> None:
    """Generate emails from prepared facts; does not crawl or send."""
    do_run(
        input_csv,
        output,
        output_format,
        model,
        max_tokens,
        system_prompt,
        prompt_template,
        delay,
        send=False,
        require_enriched=True,
        workers=workers,
    )


@app.command()
def review(
    input_csv: str = typer.Argument(help="Path to enriched or drafted CSV file"),
) -> None:
    """Review quality warnings in an enriched or drafted CSV."""
    do_review(input_csv)


# ── REPL shell ───────────────────────────────────────────────────────────────

SHELL_HELP = f"""\
{BOLD}Available commands:{RESET}

  {GREEN}discover{RESET}                       Find companies by ICP + region (with contact bundle)
      --icp <text>                What the target companies do (prompted if omitted)
      --region <text>             Country / region to target (prompted if omitted)
      --mode <companies|people>   companies (default) or legacy people-from-sources
      --find-people               Also search a named contact per company (may be stale)
      --count <number>            Max companies for LLM seeding (default: 30)
      --require-contact           Only keep companies that have an email
      -o, --output <path>         Output path (default: leads.csv)
      --limit <number>            Max companies (default: 10)
      --workers <number>          Parallel company workers, max 8 (default: 8)
      {DIM}people mode adds: [sources.txt] --source-limit --guess-role-email{RESET}

  {GREEN}run{RESET} <file.csv> [options]     Raw CSV: prepare + draft. Prepared CSV: draft again.
      -o, --output <path>         Output path (default: output.csv)
      -f, --format <csv|json|stdout>
      --max-tokens <number>
      --model <model-id>
      --system-prompt <text>      Custom system prompt
      --template <text>           Custom prompt template
      --delay <seconds>
      --workers <number>          Parallel crawl/LLM workers, max 8 (default: 5)
      --send                      Send emails via SMTP after generating

  {GREEN}prepare{RESET} <file.csv>           Verify, crawl, and enrich leads
      -o, --output <path>         Output path (default: enriched.csv)
      --max-pages <number>        Max pages per website (default: 4)
      --workers <number>          Parallel website workers (default: 8)

  {GREEN}draft{RESET} <file.csv> [options]   Generate from prepared leads only; no crawl/send
      -o, --output <path>         Output path (default: drafts.csv)
      -f, --format <csv|json|stdout>
      --workers <number>          Parallel LLM workers, max 8 (default: 5)

  {GREEN}review{RESET} <file.csv>            Show quality warnings

  {GREEN}send{RESET} <output.csv>             Send emails from a previously generated CSV
      --subject <text>            Email subject line

  {GREEN}verify{RESET} <file.csv>             Verify email addresses (format + MX)

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
        "workers": 5,
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
        elif tok == "--workers" and i + 1 < len(tokens):
            args["workers"] = int(tokens[i + 1]); i += 2
        elif tok == "--send":
            args["send"] = True; i += 1
        else:
            positional.append(tok); i += 1

    if not positional:
        return {}
    args["input_csv"] = positional[0]
    return args


def _parse_discover_args(tokens: list[str]) -> dict:
    """Parse discover subcommand arguments from REPL tokens."""
    args: dict = {
        "icp": "",
        "region": "",
        "mode": "companies",
        "output": "leads.csv",
        "limit": 10,
        "source_limit": 25,
        "require_contact": False,
        "guess_role_email": False,
        "find_people": False,
        "seed_count": 30,
        "max_pages": 3,
        "workers": 8,
    }
    positional = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--icp" and i + 1 < len(tokens):
            args["icp"] = tokens[i + 1]; i += 2
        elif tok == "--region" and i + 1 < len(tokens):
            args["region"] = tokens[i + 1]; i += 2
        elif tok == "--mode" and i + 1 < len(tokens):
            args["mode"] = tokens[i + 1]; i += 2
        elif tok in ("-o", "--output") and i + 1 < len(tokens):
            args["output"] = tokens[i + 1]; i += 2
        elif tok == "--limit" and i + 1 < len(tokens):
            args["limit"] = int(tokens[i + 1]); i += 2
        elif tok == "--source-limit" and i + 1 < len(tokens):
            args["source_limit"] = int(tokens[i + 1]); i += 2
        elif tok == "--count" and i + 1 < len(tokens):
            args["seed_count"] = int(tokens[i + 1]); i += 2
        elif tok == "--max-pages" and i + 1 < len(tokens):
            args["max_pages"] = int(tokens[i + 1]); i += 2
        elif tok == "--workers" and i + 1 < len(tokens):
            args["workers"] = int(tokens[i + 1]); i += 2
        elif tok == "--require-contact":
            args["require_contact"] = True; i += 1
        elif tok == "--guess-role-email":
            args["guess_role_email"] = True; i += 1
        elif tok == "--find-people":
            args["find_people"] = True; i += 1
        else:
            positional.append(tok); i += 1
    args["sources_file"] = positional[0] if positional else ""
    return args


def _parse_prepare_args(tokens: list[str]) -> dict:
    """Parse prepare subcommand arguments from REPL tokens."""
    args: dict = {"output": "enriched.csv", "max_pages": 4, "workers": 8}
    positional = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-o", "--output") and i + 1 < len(tokens):
            args["output"] = tokens[i + 1]; i += 2
        elif tok == "--max-pages" and i + 1 < len(tokens):
            args["max_pages"] = int(tokens[i + 1]); i += 2
        elif tok == "--workers" and i + 1 < len(tokens):
            args["workers"] = int(tokens[i + 1]); i += 2
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

            elif cmd == "discover":
                args = _parse_discover_args(rest)
                if args.get("mode") == "companies" and (not args.get("icp") or not args.get("region")):
                    if not args.get("icp"):
                        args["icp"] = _ask("What do the target companies do? (ICP)")
                    if not args.get("region"):
                        args["region"] = _ask("Which country or region?")
                    if not args.get("icp") or not args.get("region"):
                        typer.echo(f"  {DIM}ICP and region are required for companies mode.{RESET}")
                        continue
                do_discover(**args)

            elif cmd == "run":
                args = _parse_run_args(rest)
                if not args:
                    # No file specified — show interactive selector
                    csv_file = _select_csv_file()
                    if csv_file:
                        do_run(input_csv=csv_file)
                else:
                    do_run(**args)

            elif cmd == "prepare":
                args = _parse_prepare_args(rest)
                if not args:
                    csv_file = _select_csv_file()
                    if csv_file:
                        do_prepare(input_csv=csv_file)
                else:
                    do_prepare(**args)

            elif cmd == "draft":
                args = _parse_run_args(rest)
                if not args:
                    csv_file = _select_csv_file()
                    if csv_file:
                        do_run(input_csv=csv_file, output="drafts.csv", require_enriched=True)
                else:
                    if args.get("output") == "output.csv":
                        args["output"] = "drafts.csv"
                    args["require_enriched"] = True
                    do_run(**args)

            elif cmd == "review":
                if not rest:
                    typer.echo("Usage: review <file.csv>")
                else:
                    do_review(rest[0])

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

            elif cmd == "verify":
                if not rest:
                    typer.echo("Usage: verify <file.csv>")
                else:
                    do_verify(rest[0])

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
