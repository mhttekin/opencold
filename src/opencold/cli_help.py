"""Static text for the CLI: ANSI colour codes and the REPL help screen."""

# ── ANSI helpers ─────────────────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"


SHELL_HELP = f"""\
{BOLD}Available commands:{RESET}

  {GREEN}discover{RESET}                       Find companies by ICP + region (with contact bundle)
      --icp <text>                What the target companies do (prompted if omitted)
      --region <text>             Country / region to target (prompted if omitted)
      --mode <companies|people>   companies (default) or legacy people-from-sources
      --find-people               Also search a named contact per company (may be stale)
      --count <number>            Max companies for LLM seeding (default: 30)
      --no-llm                    Deterministic only — no LLM seeding or referee
      --no-wiki                   Disable the Wikipedia list channel
      --no-translate              Disable local-language search/translation
      --no-expand                 Disable semantic ICP expansion (related-term recall)
      --require-contact           Only keep companies that have an email
      -o, --output <path>         Output path (default: leads.csv)
      --limit <number>            Max companies (default: 10)
      --max-pages <number>        Company pages to crawl (default: 3)
      --workers <number>          Parallel company workers, max 8 (default: 8)
      {DIM}people mode adds: [sources.txt] --source-limit --guess-role-email{RESET}

  {GREEN}smearch{RESET} <icp> [options]      Find UK SMEs by ICP→SIC (Companies House)
      --sic <codes>               Explicit SIC code(s), comma-sep (skips matching)
      --role <type>               manufacturer / wholesaler / retailer (else asked)
      -o, --output <path>         Output CSV (default: smes.csv)
      --limit <number>            Max companies to rank (default: 50)
      -p, --page <number>         Result page, 1-based; each page is --limit (default: 1)
      --location <text>           Filter on registered office (e.g. London)
      --status <status>           Company status filter (default: active)
      --company-type <types>      Comma list (default: SME-friendly forms)
      --max-sics <number>         Max SIC codes to match (default: 5)
      --min-score <number>        Min ICP→SIC score (default: 1.0)
      --no-llm / --no-expand      Limit / disable ICP expansion
      --include-dormant           Keep dormant (non-trading) companies
      --top-n <number>            Companies to enrich + output (default: 10)
      --no-enrich                 Skip website/contacts/officers enrichment
      --size <m,s,med>            Filter by accounts size (micro/small/medium)
      --no-db                     Test run: don't skip/record already-seen companies
      --dry-run                   Preview matched SICs without querying
      {DIM}default: skips companies seen in past runs; pages on when all seen{RESET}
      {DIM}'… factories' keeps only sites with production/facility evidence{RESET}

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
