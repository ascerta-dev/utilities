# Audit and Compliance Reports

> **[Back to Documentation Index](./README.md)**

`audit-configure-ascerta-proxy.py` supports both machine-readable and human-readable reporting.

## Report Types

- JSON (`--report-format json`)
  - best for automation, policy engines, and pipelines
- Markdown (`--report-format md`)
  - best for approvals, change records, and compliance reviews

## Programmatic JSON Report

```bash
python3 audit-configure-ascerta-proxy.py --out ./audit.json
```

Primary sections:
- `summary`
- `nodes`
- `credentials_usage`
- `migration_manifest`

## Human/Compliance Markdown Report

From a live audit:

```bash
python3 audit-configure-ascerta-proxy.py \
  --report-format md \
  --out ./audit.md
```

From an existing JSON report:

```bash
python3 audit-configure-ascerta-proxy.py \
  --from-json ./audit.json \
  --report-format md \
  --out ./audit.md
```

## Recommended Artifact Pairing

For each migration batch, store both:
- `audit-<timestamp>.json`
- `audit-<timestamp>.md`

This gives deterministic machine input plus review evidence for compliance.

## Credential Capability States

- `likely_supported`: required redirect fields appear present
- `likely_unsupported`: required redirect fields appear missing
- `unverified`: API did not expose enough credential detail to confirm
- `not_applicable`: credential type is not redirect-targeted by this tool

## Migration Manifest Paths

- `already_on_ascerta`
- `credential_redirect`
- `verify_then_redirect`
- `replace_with_ascerta_proxy`
- `manual_required`

## Optional Apply Mode

The audit tool can also patch redirectable credentials.

Preview what would be patched (no changes applied):

```bash
python3 audit-configure-ascerta-proxy.py --configure-credentials --dry-run
```

Apply with interactive confirmation:

```bash
python3 audit-configure-ascerta-proxy.py --configure-credentials
```

Apply with confirmation skip (for CI/automation):

```bash
python3 audit-configure-ascerta-proxy.py --configure-credentials --yes
```

Recommended: run report-only first, then `--dry-run`, then apply with explicit review.

## Limitations and Known Issues

Review the current constraints before enterprise rollouts:
- [Limitations and Known Issues](./LIMITATIONS_AND_KNOWN_ISSUES.md)

Most important operational points:
- `unverified` capability means this n8n API did not provide enough credential detail to safely auto-classify redirect support.
- Auto-apply mode only patches credentials marked `likely_supported`.
- Migration paths in the manifest are recommendations and should be validated in staged rollout batches.

---

## See Also

- **[Command Reference](./COMMAND_REFERENCE.md)** — Full flag and option details for the audit script
- **[Getting Started](./GETTING_STARTED.md)** — Recommended operator flow including audit-first workflow
