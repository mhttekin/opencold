"""AGENTS.md invariants, enforced as tests.

Each section below maps to a rule in AGENTS.md. If one of these fails, fix the
code (or, for deliberate changes, update the rule here *and* in AGENTS.md / README.md).
"""

from __future__ import annotations

import ast
import csv
import re
from pathlib import Path
from unittest.mock import patch

import pytest
import typer.main

from opencold import cli, discovery, enricher, smearch

SRC = Path(__file__).resolve().parents[1] / "src" / "opencold"

CSV_CONTRACT_MSG = "CSV columns are a contract: update README.md and this test together."


# ── 1. CSV column contract ───────────────────────────────────────────────────


def _header(path: Path) -> list[str]:
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


DISCOVER_COMPANY_COLUMNS = [
    "email",
    "name",
    "company",
    "website",
    "match_confidence",
    "verification",
    "country",
    "region_fit",
    "company_email",
    "email_type",
    "phone",
    "address",
    "linkedin_company_url",
    "partnership_channel",
    "size_tier",
    "icp_score",
    "matched_terms",
    "website_status",
    "company_summary",
    "personalization_facts",
    "source_urls",
    "personalization_score",
    "discovery_channel",
    "discovery_source_url",
    "discovered_at",
    "lead_score",
    "lead_score_reasons",
    "quality_warnings",
]

DISCOVER_PEOPLE_EXTRA_COLUMNS = [
    "contact_name",
    "contact_role",
    "contact_linkedin",
    "contact_stale_warning",
]

DISCOVER_LEGACY_PEOPLE_COLUMNS = [
    "email",
    "first_name",
    "last_name",
    "company",
    "website",
    "discovery_source_url",
    "discovery_reason",
    "lead_score",
    "lead_score_reasons",
    "icp_score",
    "matched_terms",
    "contact_name",
    "contact_role",
    "contact_email",
    "contact_type",
    "contact_confidence",
    "contact_score",
    "contact_score_reasons",
    "contact_source_url",
    "website_status",
    "company_summary",
    "personalization_facts",
    "source_urls",
    "personalization_score",
    "quality_warnings",
]

SMEARCH_COLUMNS = [
    "sme_score",
    "company_name",
    "company_number",
    "company_status",
    "company_type",
    "incorporation_year",
    "date_of_creation",
    "account_type",
    "officer_count",
    "sic_codes",
    "matched_sic_codes",
    "matched_sic_descriptions",
    "matched_icp_terms",
    "address_line_1",
    "address_line_2",
    "locality",
    "region",
    "postal_code",
    "country",
    "company_url",
    "officer_names",
    "website",
    "website_confidence",
    "address_matched",
    "phone",
    "email",
    "email_type",
    "contact_source",
]

# prepare passes input columns through, then appends these (in this order).
PREPARE_INPUT_COLUMNS = ["company", "website", "email", "name"]
PREPARE_ADDED_COLUMNS = [
    "verification_status",
    "website_status",
    "company_summary",
    "personalization_facts",
    "source_urls",
    "personalization_score",
    "quality_warnings",
    "enrichment_json",
]

# run/draft (legacy) pass input columns through, then append these.
DRAFT_ADDED_COLUMNS = ["quality_warnings", "generated_subject", "generated_email"]


class TestCsvContract:
    def test_discover_companies(self, tmp_path):
        rows = [
            {"company": "Acme", "website": "https://acme.test", "match_confidence": "verified"},
            {"company": "Beta", "website": "https://beta.test", "match_confidence": "review"},
        ]
        out = tmp_path / "leads.csv"
        discovery.write_company_csv(rows, str(out))
        assert _header(out) == DISCOVER_COMPANY_COLUMNS, CSV_CONTRACT_MSG

    def test_discover_companies_with_people(self, tmp_path):
        rows = [{"company": "Acme", "match_confidence": "verified", "contact_name": "Ada"}]
        out = tmp_path / "leads.csv"
        discovery.write_company_csv(rows, str(out))
        expected = DISCOVER_COMPANY_COLUMNS + DISCOVER_PEOPLE_EXTRA_COLUMNS
        assert _header(out) == expected, CSV_CONTRACT_MSG

    def test_discover_people_mode(self, tmp_path):
        rows = [{"email": "ada@acme.test", "company": "Acme"}]
        out = tmp_path / "leads.csv"
        discovery.write_csv(rows, str(out))
        assert _header(out) == DISCOVER_LEGACY_PEOPLE_COLUMNS, CSV_CONTRACT_MSG

    def test_smearch(self, tmp_path):
        rows = [{"company_name": "ACME LTD", "company_number": "01234567", "stray_ch_key": "x"}]
        out = tmp_path / "smes.csv"
        smearch.write_smes_csv(rows, str(out))
        assert _header(out) == SMEARCH_COLUMNS, CSV_CONTRACT_MSG

    def test_prepare(self, tmp_path):
        row = {
            "company": "Acme",
            "website": "https://acme.test",
            "email": "a@acme.test",
            "name": "Ada",
        }
        with (
            patch("opencold.enricher.crawl_site", return_value=[]),
            patch(
                "opencold.enricher.verifier.verify_email",
                return_value={"valid": True, "reason": ""},
            ),
        ):
            enriched = [enricher.enrich_row(row)]
        out = tmp_path / "enriched.csv"
        enricher.write_csv(enriched, str(out))
        assert _header(out) == PREPARE_INPUT_COLUMNS + PREPARE_ADDED_COLUMNS, CSV_CONTRACT_MSG

    def test_run_and_draft(self, tmp_path):
        rows = [{"company": "Acme", "email": "a@acme.test", "name": "Ada"}]
        results = [dict(rows[0], generated_subject="Hi", generated_email="Body")]
        out = tmp_path / "drafts.csv"
        cli._write_results(rows, results, str(out), "csv")
        expected = ["company", "email", "name"] + DRAFT_ADDED_COLUMNS
        assert _header(out) == expected, CSV_CONTRACT_MSG


# ── 2. CLI flag sync: Typer ↔ REPL parser ↔ REPL help ────────────────────────

# Typer command → REPL parser that handles it.
REPL_PARSERS = {
    "discover": "_parse_discover_args",
    "smearch": "_parse_smearch_args",
    "run": "_parse_run_args",
    "draft": "_parse_run_args",
    "prepare": "_parse_prepare_args",
    "send": "_parse_send_args",
}

# Positional tokens each parser needs before it returns anything.
BASE_TOKENS = {
    "discover": [],
    "smearch": ["acme"],
    "run": ["in.csv"],
    "draft": ["in.csv"],
    "prepare": ["in.csv"],
    "send": ["in.csv"],
}

# (command, kind, flag) → why the difference is deliberate.
# kind: "not_in_parser" | "not_in_help" | "not_in_typer"
_LEGACY = "legacy email flow, not maintained"
ALLOWED_DIFFERENCES: dict[tuple[str, str, str], str] = {
    ("smearch", "not_in_help", "--sandbox"): "dev-only, intentionally hidden from REPL help",
    ("draft", "not_in_help", "--model"): _LEGACY,
    ("draft", "not_in_help", "--max-tokens"): _LEGACY,
    ("draft", "not_in_help", "--system-prompt"): _LEGACY,
    ("draft", "not_in_help", "--template"): _LEGACY,
    ("draft", "not_in_help", "--delay"): _LEGACY,
    ("draft", "not_in_typer", "--send"): (
        "draft shares run's parser; the REPL rejects --send for draft "
        "(tests/test_cli.py::TestDraftNeverSends)"
    ),
}

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


INTROSPECTION_MSG = "Typer introspection found no options: Typer/Click API changed?"


def _typer_options() -> dict[str, list[tuple[str, bool]]]:
    """{command: [(flag, is_flag), ...]} for every top-level Typer command.

    Duck-typed on purpose: Typer >=0.29 vendors Click (typer._click), so
    isinstance checks against the public `click` classes silently match nothing.
    """
    root = typer.main.get_command(cli.app)
    out: dict[str, list[tuple[str, bool]]] = {}
    for name, cmd in root.commands.items():
        if hasattr(cmd, "commands"):  # a group (config/profile/provider/smtp)
            continue
        out[name] = [
            (flag, bool(getattr(p, "is_flag", False)))
            for p in cmd.params
            if getattr(p, "param_type_name", None) == "option" and p.name != "help"
            for flag in p.opts + p.secondary_opts
        ]
    found = {f for opts in out.values() for f, _ in opts}
    assert found and "--icp" in {f for f, _ in out.get("discover", [])}, INTROSPECTION_MSG
    return out


def _parser_flags(func_name: str) -> set[str]:
    """Flags a REPL parser compares `tok` against (static, via ast)."""
    tree = ast.parse((SRC / "cli.py").read_text())
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func_name)
    flags: set[str] = set()
    for node in ast.walk(func):
        if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)):
            continue
        if node.left.id != "tok":
            continue
        for comp in node.comparators:
            consts = comp.elts if isinstance(comp, ast.Tuple) else [comp]
            for c in consts:
                if isinstance(c, ast.Constant) and str(c.value).startswith("-"):
                    flags.add(c.value)
    return flags


def _parser_accepts(cmd: str, flag: str, is_flag: bool) -> bool:
    """Feed the flag to the REPL parser; accepted iff it changes the result and
    doesn't leak into a positional value (unknown flags become positionals)."""
    parse = getattr(cli, REPL_PARSERS[cmd])
    base = BASE_TOKENS[cmd]
    baseline = parse(list(base))
    tokens = list(base) + [flag] + ([] if is_flag else ["7"])
    try:
        result = parse(tokens)
    except Exception:
        return False
    leaked = any(isinstance(v, str) and flag in v for v in result.values())
    return result != baseline and not leaked


def _help_sections() -> dict[str, str]:
    """REPL help text split per command (a line at 2-space indent starts one)."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in _ANSI.sub("", cli.SHELL_HELP).splitlines():
        m = re.match(r"^  (\S+)", line)
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
        if current:
            sections[current].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def _mentions(text: str, flag: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text) is not None


def _flag_differences() -> set[tuple[str, str, str]]:
    typer_opts = _typer_options()
    help_sections = _help_sections()
    diffs: set[tuple[str, str, str]] = set()
    for cmd, parser in REPL_PARSERS.items():
        opts = typer_opts[cmd]
        typer_flags = {f for f, _ in opts}
        for flag, is_flag in opts:
            if not _parser_accepts(cmd, flag, is_flag):
                diffs.add((cmd, "not_in_parser", flag))
            if not _mentions(help_sections.get(cmd, ""), flag):
                diffs.add((cmd, "not_in_help", flag))
        for flag in _parser_flags(parser) - typer_flags:
            diffs.add((cmd, "not_in_typer", flag))
    return diffs


class TestCliFlagSync:
    def test_every_command_with_options_has_a_repl_parser(self):
        with_opts = {c for c, opts in _typer_options().items() if opts}
        assert with_opts <= set(REPL_PARSERS), (
            f"Commands with options but no REPL parser mapping: {sorted(with_opts - set(REPL_PARSERS))}"
        )

    def test_typer_parser_help_in_sync(self):
        unexpected = sorted(_flag_differences() - set(ALLOWED_DIFFERENCES))
        assert not unexpected, (
            "CLI flags live in three places (Typer signature, _parse_<cmd>_args(), "
            "SHELL_HELP); change all three. Out of sync: "
            + ", ".join(f"{c} {f} ({k})" for c, k, f in unexpected)
        )

    def test_allowed_differences_are_not_stale(self):
        stale = sorted(set(ALLOWED_DIFFERENCES) - _flag_differences())
        assert not stale, f"These ALLOWED_DIFFERENCES no longer apply; delete them: {stale}"


# ── 3. pipeline.py stays headless ────────────────────────────────────────────

HEADLESS_MSG = "pipeline.py must stay headless (see AGENTS.md)."
FORBIDDEN_CALLS = {"print", "input", "open"}
FORBIDDEN_METHODS = {"write_text", "write_bytes"}
FORBIDDEN_MODULES = {"typer", "click", "rich", "prompt_toolkit"}


def _headless_violations(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in FORBIDDEN_CALLS:
                found.append(f"line {node.lineno}: call to {fn.id}()")
            elif isinstance(fn, ast.Attribute) and fn.attr in FORBIDDEN_METHODS:
                found.append(f"line {node.lineno}: call to .{fn.attr}()")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in FORBIDDEN_MODULES or alias.name in ("config", "opencold.config"):
                    found.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.split(".")[0] in FORBIDDEN_MODULES or mod in ("config", "opencold.config"):
                found.append(f"line {node.lineno}: from {mod} import ...")
            elif mod in ("opencold", "") and any(a.name == "config" for a in node.names):
                found.append(f"line {node.lineno}: from {mod or '.'} import config")
    return found


def test_pipeline_is_headless():
    violations = _headless_violations((SRC / "pipeline.py").read_text())
    assert not violations, "; ".join(violations) + ". " + HEADLESS_MSG


@pytest.mark.parametrize(
    "snippet",
    [
        'print("x")',
        "input()",
        'open("f", "w")',
        'Path("f").write_text("x")',
        "import typer",
        "from rich.console import Console",
        "from opencold import config",
        "from . import config",
        "import prompt_toolkit.shortcuts",
    ],
)
def test_headless_checker_catches(snippet):
    assert _headless_violations(snippet), f"checker missed: {snippet}"


# ── 4. Module size ratchet ───────────────────────────────────────────────────

MAX_LINES = 400
SIZE_MSG = (
    "Split the module instead of growing it. "
    "If you shrank a grandfathered file, lower its number here."
)
# Pure data (constants only, no logic): exempt.
DATA_MODULES = {"sic_data.py", "regions_data.py", "cli_help.py"}
# Logic modules already over the limit on 2026-11-10. They may not grow.
GRANDFATHERED = {
    "discovery.py": 2579,
    "cli.py": 3017,
    "config.py": 519,
    "pipeline.py": 502,
    "icp_synonyms.py": 483,
    "smearch.py": 476,
    "icp_expansion.py": 470,
    "sic_match.py": 436,
}


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_module_size_ratchet():
    problems = []
    for path in sorted(SRC.glob("*.py")):
        name = path.name
        if name in DATA_MODULES:
            continue
        n = _line_count(path)
        limit = GRANDFATHERED.get(name, MAX_LINES)
        if n > limit:
            problems.append(f"{name} has {n} lines (limit {limit})")
        elif name in GRANDFATHERED and n < limit:
            if n > MAX_LINES:
                problems.append(f"{name} shrank to {n} lines: set GRANDFATHERED to {n}")
            else:
                problems.append(f"{name} is now {n} lines: remove it from GRANDFATHERED")
    assert not problems, "; ".join(problems) + ". " + SIZE_MSG


def test_ratchet_lists_only_existing_files():
    missing = sorted(n for n in GRANDFATHERED.keys() | DATA_MODULES if not (SRC / n).exists())
    assert not missing, f"Listed in GRANDFATHERED/DATA_MODULES but missing: {missing}"
