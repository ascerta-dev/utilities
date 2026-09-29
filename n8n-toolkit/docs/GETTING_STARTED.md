# Getting Started

> **[Back to Documentation Index](./README.md)**

## 1) Prerequisites

- **n8n API access**
  - `N8N_BASE_URL` (e.g. `http://localhost:5678`)
  - `N8N_API_KEY` (create in n8n: Settings > API > Create API Key)
- **Ascerta access** (needed for credential patch/apply)
  - `ASCERTA_BASE_URL` (e.g. `https://api.ascerta.com`)
  - `ASCERTA_API_KEY`
- **Python 3.10+** (CI tests 3.10 and 3.12; Docker image uses 3.12-slim)
- **Bash + curl** (for shell redirect scripts)
- **@ascerta/n8n-nodes-ascerta community node** (required for node replacement migration)
  - Install via n8n UI: **Settings > Community Nodes > Install** > enter `@ascerta/n8n-nodes-ascerta`
  - Or manually: `cd ~/.n8n/nodes && npm install @ascerta/n8n-nodes-ascerta`, then restart n8n
  - For AI Agent support, start n8n with: `N8N_COMMUNITY_PACKAGES_ALLOW_TOOL_USAGE=true`
  - Full details: [@ascerta/n8n-nodes-ascerta on GitHub](https://github.com/ascerta-dev/n8n-nodes-ascerta)
  - Note: credential redirect migration works without this package installed.

Notes:
- Python scripts are interactive by default and prompt for missing required values.
- For CI/pipelines, set all four env vars plus `--auto-yes` and `--strategy` for the migration script, or `--non-interactive` for the audit script.

## 2) Recommended Operator Flow

1. **Back up** workflows and credential metadata before any apply-mode operation (see "Before Applying Changes" below).
2. Run audit in read-only mode.
3. Review [Limitations and Known Issues](./LIMITATIONS_AND_KNOWN_ISSUES.md).
4. Review `migration_manifest` and credential capability states.
5. Treat `unverified` credentials as manual validation items before apply mode.
6. Decide migration strategy:
   - credential redirect
   - node replacement
   - both
7. Run migration in dry-run mode first.
8. Apply in controlled batches.
9. Validate workflow execution and tracking output.

## Before Applying Changes

- **Export workflow backups:** n8n UI > Workflows > select all > Export, or use the n8n API.
- **For credential redirect:** note the current base URL values for each credential before running any apply-mode command. Revert values if needed:
  - OpenAI: `https://api.openai.com/v1`
  - Anthropic: `https://api.anthropic.com` (and remove `xProxy-api-key` header)
  - Azure OpenAI: your original Azure resource endpoint
- **For node replacement:** migrated workflows are created as new copies (renamed with a "(Ascerta)" suffix). Original workflows are preserved unless you delete them manually.
- **Credential patches are not transactional.** If a batch fails mid-run, some credentials may be redirected while others are not. Review credential state after any failure.

## 3) Read-Only Audit

```bash
python3 audit-configure-ascerta-proxy.py --out ./audit.json
```

Generate Markdown from JSON for review/compliance:

```bash
python3 audit-configure-ascerta-proxy.py \
  --from-json ./audit.json \
  --report-format md \
  --out ./audit.md
```

## 4) Interactive Migration Orchestrator

```bash
python3 migrate-workflows-to-ascerta.py
```

The script guides you through:
- connection setup,
- workflow scan,
- strategy selection (`redirect`, `replace`, `both`),
- credentials and apply flow.

Dry-run:

```bash
python3 migrate-workflows-to-ascerta.py --dry-run
```

## 5) Redirect-Only Scripts

These shell scripts require the same four env vars as the Python scripts (`N8N_BASE_URL`, `N8N_API_KEY`, `ASCERTA_BASE_URL`, `ASCERTA_API_KEY`). Note: `migrate-openai-to-ascerta.sh` treats `ASCERTA_API_KEY` as optional (prints a reminder if unset but continues).

All supported credentials:

```bash
export N8N_BASE_URL="http://localhost:5678"
export N8N_API_KEY="your-key"
export ASCERTA_BASE_URL="https://api.ascerta.com"
export ASCERTA_API_KEY="your-ascerta-key"

./migrate-to-ascerta.sh
```

OpenAI only:

```bash
./migrate-openai-to-ascerta.sh
```

## 6) Validation Checklist

- Workflows still execute successfully
- Expected credentials are attached to migrated nodes
- Expected requests route through Ascerta proxy
- Cost/usage/tracking data appears as expected
- No broken expression references

---

## Next Steps

- **[Command Reference](./COMMAND_REFERENCE.md)** — Full details on every flag and option
- **[Audit and Compliance Reports](./AUDIT_AND_REPORTS.md)** — Generating and interpreting audit artifacts
- **[Limitations and Known Issues](./LIMITATIONS_AND_KNOWN_ISSUES.md)** — Read before any production rollout
