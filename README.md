# OpenCold

CLI tool for generating personalized cold outreach emails using LLMs. Supports multiple providers (Anthropic, OpenAI, and any OpenAI-compatible proxy like HuggingFace, DeepInfra, Ollama, etc.).

## Installation

```bash
pip install -e .
```

For development:
```bash
pip install -e ".[dev]"
```

## Quick Start

```bash
opencold
```

This launches an interactive shell. On first run, it will walk you through setup (API key, identity, profile).

### Setup

```
config init          # Interactive setup: identity, API key, profile
provider add         # Add a provider (Anthropic, OpenAI, or Proxy)
provider default <n> # Set default provider
```

### Generate Emails

Prepare a CSV with columns: `email`, `first_name`, `last_name`, `company`, `website` (optional).

```
run leads.csv
run leads.csv --model claude-opus-4-6 --max-tokens 2048
run leads.csv -o results.json -f json
```

The tool will:
1. Validate the CSV (email required, warns about missing websites)
2. Scrape each company's website for context
3. Generate a personalized 3-paragraph email per lead
4. Append the sender's name as sign-off
5. Write results to the output file

### Profiles

Manage multiple sender identities (different companies, pitches, campaigns):

```
profile create startup-pitch
profile use startup-pitch
profile list
profile delete old-profile
```

### Providers

```
provider list              # Show configured providers
provider add               # Interactive: Anthropic, OpenAI, or Proxy
provider delete <name>     # Remove a provider
provider default <name>    # Set default for runs
```

The `--model` flag auto-detects the provider from the model name (`claude-*` -> Anthropic, `gpt-*` -> OpenAI, others -> matching proxy).

## Run Options

| Flag | Description |
|------|-------------|
| `-o, --output <path>` | Output file path (default: `output.csv`) |
| `-f, --format <csv\|json\|stdout>` | Output format |
| `--model <id>` | Model ID (auto-detects provider) |
| `--max-tokens <n>` | Override max tokens for generation |
| `--system-prompt <text>` | Custom system prompt |
| `--template <text>` | Custom prompt template |
| `--delay <seconds>` | Delay between requests (default: 0.5) |

## CSV Format

Required columns:
- `email` - recipient email address
- `first_name` - recipient first name
- `last_name` - recipient last name
- `company` - recipient company name

Optional columns:
- `website` - company website URL (used for personalization)

## Running Tests

```bash
pytest
```

## License

MIT
