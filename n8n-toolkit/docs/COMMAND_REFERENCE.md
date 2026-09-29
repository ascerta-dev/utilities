# Command Reference

> **[Back to Documentation Index](./README.md)**

## `audit-configure-ascerta-proxy.py`

Audit workflows and emit migration/compliance reports.

### Typical Use

```bash
python3 audit-configure-ascerta-proxy.py --out ./audit.json
```

### Key Options

- `--workflow ID`: analyze only one workflow
- `--from-json PATH`: load an existing JSON report instead of calling n8n API
- `--out PATH`: write report to file
- `--report-format json|md`: output format for `--out`
- `--json`: print report JSON to stdout
- `--configure-credentials`: patch credentials that are marked redirectable
- `--dry-run`: preview credential patch actions without applying
- `--yes`: skip apply confirmation prompt
- `--non-interactive`: fail if required inputs are missing (no prompts; recommended for CI/pipelines)
- `--n8n-base-url URL`, `--n8n-api-key KEY`
- `--ascerta-base-url URL`, `--ascerta-api-key KEY`
- `--verbose`: show API call logs
- `--insecure`: disable TLS verification (local/self-signed environments only; never use in production)

### Current Constraints

- `--configure-credentials` cannot be combined with `--from-json`.
- Auto-apply patches only credentials with `redirect_capability=likely_supported`.
- `unverified` credentials require manual validation before apply.
- Detection scope is limited to mapped native/Ascerta node types.
- Full details: [Limitations and Known Issues](./LIMITATIONS_AND_KNOWN_ISSUES.md)

## `migrate-workflows-to-ascerta.py`

Interactive migration orchestrator for redirect and/or node replacement.

### Typical Use

```bash
python3 migrate-workflows-to-ascerta.py
```

### Key Options

- `--dry-run`: preview without writing
- `--auto-yes`: skip interactive node/workflow selection where possible
- `--workflow ID`: limit migration to one workflow
- `--strategy redirect|replace|both`: pre-select migration strategy
- `--verbose`: show detailed API logs and credential verification details

### CI/Pipeline Usage

This script does not have a `--non-interactive` flag. For unattended use, set all four environment variables (`N8N_BASE_URL`, `N8N_API_KEY`, `ASCERTA_BASE_URL`, `ASCERTA_API_KEY`) and combine `--auto-yes` with `--strategy`:

```bash
python3 migrate-workflows-to-ascerta.py --auto-yes --strategy both
```

### Strategy Modes

- `redirect`: patch redirectable credentials to Ascerta proxy URLs
- `replace`: replace supported nodes with Ascerta nodes
- `both`: run redirect + replacement

## `migrate-to-ascerta.sh`

Bulk credential redirect script.

### Required Environment Variables

All four must be set: `N8N_BASE_URL`, `N8N_API_KEY`, `ASCERTA_BASE_URL`, `ASCERTA_API_KEY`.

### Behavior

- Scans credentials in n8n
- Targets `openAiApi`, `anthropicApi`, `azureOpenAiApi`
- Prompts for provider API key values before patching

## `migrate-openai-to-ascerta.sh`

OpenAI-only credential redirect script.

### Required Environment Variables

`N8N_BASE_URL`, `N8N_API_KEY`, `ASCERTA_BASE_URL` are required. `ASCERTA_API_KEY` is optional (a reminder is printed if unset, but the script continues).

---

## See Also

- **[Getting Started](./GETTING_STARTED.md)** — Prerequisites and recommended operator flow
- **[Audit and Compliance Reports](./AUDIT_AND_REPORTS.md)** — Report generation workflows and artifact pairing
- **[Limitations and Known Issues](./LIMITATIONS_AND_KNOWN_ISSUES.md)** — Constraints that affect how commands behave
