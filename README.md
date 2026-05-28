# OpenCold

CLI tool for generating and sending personalized cold outreach emails using LLMs. Supports multiple providers (Anthropic, OpenAI, and any OpenAI-compatible proxy like HuggingFace, Novita, DeepInfra, Ollama, etc.).

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
run leads.csv --send   # Generate and send immediately
```

The tool will:
1. Validate the CSV (email required, warns about missing websites)
2. Scrape each company's website for context
3. Generate a personalized 3-paragraph email per lead with an AI-generated subject line
4. Append the sender's name as sign-off
5. Write results to the output file (includes `generated_subject` and `generated_email` columns)

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

The `--model` flag auto-detects the provider from the model name (`claude-*` -> Anthropic, `gpt-*` -> OpenAI). For unknown model names, the tool routes to a configured proxy provider. If multiple proxies exist, it prompts you to choose.

## Sending Emails (SMTP)

OpenCold can send generated emails directly via SMTP. There are two ways to send:

```
run leads.csv --send                     # Generate and send in one step
send output.csv                          # Send from a previously generated CSV
send output.csv --subject "Quick call"   # Override subject for all emails
```

Subject lines are generated automatically by the LLM alongside each email. You can override them with `--subject` when using the `send` command.

### SMTP Setup

Run `smtp setup` in the interactive shell. The wizard will guide you through configuration.

```
smtp setup    # Interactive SMTP configuration
smtp test     # Test connection
smtp show     # Show saved config (password masked)
```

If you try to send without SMTP configured, the setup wizard launches automatically.

### Gmail Setup

Gmail requires an **App Password** — your regular Google password will not work.

1. Enable [2-Step Verification](https://myaccount.google.com/signinoptions/two-step-verification) on your Google account
2. Go to [App Passwords](https://myaccount.google.com/apppasswords)
3. Select **Mail** (or **Other**), then click **Generate**
4. Copy the 16-character password

Use these settings in `smtp setup`:

| Setting | Value |
|---------|-------|
| Host | `smtp.gmail.com` |
| Port | `587` |
| Username | your full Gmail address |
| Password | the 16-character app password |
| TLS | Yes |

> Google may disable App Passwords if 2-Step Verification is turned off. Keep it enabled.

### Outlook / Microsoft 365 Setup

Outlook also requires an App Password if you have 2-Step Verification enabled.

1. Go to [Microsoft Security](https://account.microsoft.com/security)
2. Select **Advanced security options** > **App passwords**
3. Create a new app password and copy it

| Setting | Value |
|---------|-------|
| Host | `smtp.office365.com` |
| Port | `587` |
| Username | your full Outlook/Microsoft email |
| Password | app password (or regular password if 2FA is off) |
| TLS | Yes |

> Some Microsoft 365 organizations disable SMTP AUTH. If connection fails, check with your IT admin or see [Microsoft's SMTP AUTH guide](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/authenticated-client-smtp-submission).

### Zoho Mail Setup

| Setting | Value |
|---------|-------|
| Host | `smtp.zoho.com` |
| Port | `587` |
| Username | your Zoho email |
| Password | your Zoho password (or app password if 2FA is on) |
| TLS | Yes |

> If using a custom domain with Zoho, use `smtppro.zoho.com` instead.

### Other Providers

Any standard SMTP server works. Use `smtp setup` and enter your provider's SMTP host, port, and credentials. Common ports:

- **587** — STARTTLS (recommended)
- **465** — SSL/TLS
- **25** — Unencrypted (not recommended)

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
| `--send` | Send emails via SMTP after generating |

## CSV Format

Required columns:
- `email` - recipient email address
- `first_name` - recipient first name
- `last_name` - recipient last name
- `company` - recipient company name

Optional columns:
- `website` - company website URL (used for personalization)

Output adds:
- `generated_subject` - Generated subject line
- `generated_email` - Generated email body

## Running Tests

```bash
pytest
```

## License

MIT
