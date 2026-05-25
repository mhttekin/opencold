"""OpenCold CLI — cold outreach email generator powered by Claude."""

import csv
import json
import shlex
import sys
import time
from typing import Optional

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings

from opencold import config, crawler, generator
from opencold.prompts import (
    Category,
    SYSTEM_PROMPTS,
    build_user_prompt,
    build_template_prompt,
    category_label,
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


def _collect_context(category: Category) -> dict:
    saved = config.get_campaign(category.value)
    if saved and (saved.get("description") or saved.get("pitch")):
        typer.echo(f"\n  Last {category_label(category)} campaign settings:\n")
        if saved.get("description"):
            typer.echo(f"    {DIM}Description:{RESET} {saved['description']}")
        if saved.get("pitch"):
            typer.echo(f"    {DIM}Pitch:{RESET}       {saved['pitch']}")
        typer.echo("")
        if _confirm("Use these settings?", default=True):
            return saved

    prof = config.get_profile()
    default_bio = (saved or {}).get("description") or prof.get("bio", "")
    default_pitch = (saved or {}).get("pitch") or prof.get("pitch", "")
    typer.echo(f"\n  Context for {category_label(category)} outreach {DIM}(ESC to cancel){RESET}\n")
    description = _ask("Briefly describe what you / your company does", default=default_bio)
    pitch = _ask("What's the key message or pitch for this outreach?", default=default_pitch)

    ctx = {"description": description, "pitch": pitch}
    config.set_campaign(category.value, ctx)
    return ctx


def _has_enough_context(ctx: dict) -> bool:
    return bool(ctx.get("description") and ctx.get("pitch"))


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
    client = generator.create_client(api_key)

    use_flags = system_prompt is not None or prompt_template is not None
    category = None
    context = None

    if use_flags:
        sys_prompt = system_prompt or SYSTEM_PROMPTS[Category.sales]
    else:
        typer.echo(f"\n  Select outreach category {DIM}(ESC to cancel){RESET}\n")
        for i, cat in enumerate(Category, 1):
            typer.echo(f"    {i}. {category_label(cat)}")
        choice = _ask("\n  Category", default="1")
        idx = max(0, min(int(choice) - 1, len(Category) - 1))
        category = list(Category)[idx]
        typer.echo(f"\n  Selected: {category_label(category)}")
        sys_prompt = SYSTEM_PROMPTS[category]
        context = _collect_context(category)

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
        elif context and _has_enough_context(context):
            user_prompt = build_user_prompt(row, identity, profile, category, context, website_text)
        else:
            user_prompt = build_template_prompt(row, identity, profile, category)

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
    system_prompt: Optional[str] = typer.Option(None, "--system-prompt", help="Custom system prompt (Path A)"),
    prompt_template: Optional[str] = typer.Option(None, "--template", help="Custom prompt template (Path A)"),
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
      --system-prompt <text>      Path A: custom system prompt
      --template <text>           Path A: custom prompt template
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

    session = PromptSession(history=InMemoryHistory())

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
                    typer.echo("Usage: run <file.csv> [options]")
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
