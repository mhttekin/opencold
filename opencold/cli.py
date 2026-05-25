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

from opencold import config, crawler, generator
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


# ── ESC-cancellable prompts ─────────────────────────────────────────────────


class Cancelled(Exception):
    """Raised when user presses ESC to cancel a prompt."""


def _esc_bindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("escape", eager=True)
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

    _TOP_COMMANDS = ["run", "config", "profile", "help", "exit", "quit"]
    _CONFIG_SUBS = ["init", "set-key"]
    _PROFILE_SUBS = ["list", "create", "use", "delete"]
    # Subcommands that accept a profile name as 3rd argument
    _PROFILE_NAME_SUBS = {"use", "delete"}

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

        # After "run", complete file paths (CSV files)
        if first == "run":
            prefix_len = len(words[0]) + 1
            from prompt_toolkit.document import Document
            sub_text = text[prefix_len:] if len(text) > prefix_len else ""
            sub_doc = Document(sub_text)
            yield from self._path_completer.get_completions(sub_doc, complete_event)


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
            typer.echo(f"{'='*60}")
            typer.echo(r["generated_email"])
    else:
        fieldnames = list(rows[0].keys()) + ["generated_email"]
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
    model: str = generator.DEFAULT_MODEL,
    max_tokens: int = generator.DEFAULT_MAX_TOKENS,
    system_prompt: str | None = None,
    prompt_template: str | None = None,
    delay: float = 0.5,
) -> None:
    """Core run logic shared by the CLI command and the REPL."""
    _ensure_config()
    api_key = config.get_api_key("anthropic")
    identity = config.get_identity()
    profile = config.get_profile()

    rows = _read_csv(input_csv)

    # Validate email and website columns
    rows = _validate_csv(rows)
    if rows is None:
        return

    client = generator.create_client(api_key)

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
        urls = {row["website"] for row in rows if row.get("website", "").strip()}
        if urls:
            typer.echo(f"\n  Crawling {len(urls)} website(s)...\n")
            for url in urls:
                typer.echo(f"    {url} ... ", nl=False)
                text = crawler.crawl_website(url)
                website_cache[url] = text
                if text:
                    typer.echo(f"ok ({len(text)} chars)")
                else:
                    typer.echo("skipped (no content)")

    typer.echo(f"\n  Processing {len(rows)} contacts with '{model}'...\n")
    results = []

    for i, row in enumerate(rows, 1):
        name = f"{row['first_name']} {row['last_name']}"
        typer.echo(f"  [{i}/{len(rows)}] {name} ({row['company']})... ", nl=False)

        website_text = None
        if has_websites:
            website_text = website_cache.get(row.get("website", ""))

        if use_flags and prompt_template:
            user_prompt = prompt_template.format(**row)
        elif use_flags:
            user_prompt = (
                f"Write a cold outreach email to {row['first_name']} {row['last_name']} "
                f"at {row['company']}. Their email is {row['email']}."
            )
        elif campaign and _has_enough_context(campaign):
            user_prompt = build_user_prompt(row, identity, profile, campaign, website_text)
        else:
            user_prompt = build_template_prompt(row, identity, profile)

        try:
            email_text = generator.generate_with_retry(
                client, sys_prompt, user_prompt, model, max_tokens
            )
            results.append({**row, "generated_email": email_text})
            typer.echo("done")
        except Exception as e:
            typer.echo(f"failed: {e}")
            results.append({**row, "generated_email": f"ERROR: {e}"})

        if i < len(rows):
            time.sleep(delay)

    _write_results(rows, results, output, output_format)

    success = sum(1 for r in results if not r["generated_email"].startswith("ERROR:"))
    typer.echo(f"\n  Done! {success}/{len(rows)} emails generated.")
    if output_format == "csv" and output != "-":
        typer.echo(f"  Output saved to: {output}")


# ── typer run command (for direct CLI usage) ─────────────────────────────────


@app.command()
def run(
    input_csv: str = typer.Argument(help="Path to input CSV file"),
    output: str = typer.Option("output.csv", "-o", "--output", help="Output path (use '-' for stdout)"),
    output_format: str = typer.Option("csv", "-f", "--format", help="Output format: csv, json, stdout"),
    model: str = typer.Option(generator.DEFAULT_MODEL, "--model", help="Claude model ID"),
    max_tokens: int = typer.Option(generator.DEFAULT_MAX_TOKENS, "--max-tokens"),
    system_prompt: Optional[str] = typer.Option(None, "--system-prompt", help="Custom system prompt"),
    prompt_template: Optional[str] = typer.Option(None, "--template", help="Custom prompt template"),
    delay: float = typer.Option(0.5, "--delay"),
) -> None:
    """Generate personalized cold outreach emails from a CSV."""
    do_run(input_csv, output, output_format, model, max_tokens, system_prompt, prompt_template, delay)


# ── REPL shell ───────────────────────────────────────────────────────────────

SHELL_HELP = f"""\
{BOLD}Available commands:{RESET}

  {GREEN}run{RESET} <file.csv> [options]     Generate emails from a CSV
      -o, --output <path>         Output path (default: output.csv)
      -f, --format <csv|json|stdout>
      --model <model-id>
      --system-prompt <text>      Custom system prompt
      --template <text>           Custom prompt template
      --delay <seconds>

  {GREEN}config{RESET}                        Show current configuration
  {GREEN}config init{RESET}                  Set up API key & profile info
  {GREEN}config set-key{RESET} [provider]    Set an API key

  {GREEN}profile list{RESET}                 List all profiles
  {GREEN}profile create{RESET} <name>        Create a new profile
  {GREEN}profile use{RESET} <name>           Switch to a profile
  {GREEN}profile delete{RESET} <name>        Delete a profile

  {GREEN}help{RESET}                         Show this help
  {GREEN}exit{RESET} / {GREEN}quit{RESET}                    Exit the shell

  {DIM}Press ESC during any prompt to cancel.{RESET}
"""


def _parse_run_args(tokens: list[str]) -> dict:
    """Parse run subcommand arguments from REPL tokens."""
    args: dict = {
        "output": "output.csv",
        "output_format": "csv",
        "model": generator.DEFAULT_MODEL,
        "max_tokens": generator.DEFAULT_MAX_TOKENS,
        "system_prompt": None,
        "prompt_template": None,
        "delay": 0.5,
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
            line = session.prompt(ANSI(_prompt_str())).strip()
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
            if cmd in ("exit", "quit"):
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
