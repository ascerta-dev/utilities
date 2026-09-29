# Changelog for Operators

> **[Back to Documentation Index](./README.md)**

This changelog is for platform operators running migrations and audits in n8n environments.
It focuses on operational impact, required actions, and rollout risk.

## 2026-09-29

### Changed
- Install `@ascerta/n8n-nodes-ascerta` for replacement migrations. Generated
  workflow types now use the `@ascerta/n8n-nodes-ascerta.*` namespace and
  Ascerta credential types.
- Script names now use `ascerta`; environment variables previously prefixed
  with the former brand now use `ASCERTA_`. Update existing runbooks and CI jobs.
- Databricks replacements use `ascertaDatabricksApi`; native `databricks`
  credentials cannot be copied to the Ascerta node. Review custom endpoint
  **Deployed Model** values before running migrated workflows.

---

## 2026-03-06

### Added
- **Databricks provider support** across migration and audit tooling:
  - Migration script detects and replaces three native Databricks node types:
    `n8n-nodes-databricks.databricks`, `n8n-nodes-databricks.lmChatDatabricks`,
    `n8n-nodes-databricks.databricksAiAgent`
  - Builds Ascerta Databricks replacement nodes (`lmChatAscertaDatabricks`)
  - Audit script now flags Databricks community nodes with `replace_with_ascerta_node` recommendation
- Databricks credential provisioning support in `PROVIDER_CREDENTIAL_CONFIG`
  (fields: `token`, `host`; env vars: `DATABRICKS_TOKEN`, `DATABRICKS_WORKSPACE_URL`)
- Test coverage for Databricks detection, node building, credential passthrough,
  and option filtering (157 tests total, all passing)

### Changed
- Documentation updates across getting started guide, command reference,
  audit reports, and workflow fixtures

### Operational Impact
- Operators can now migrate Databricks community node workflows to Ascerta
  with the same `--dry-run` / apply workflow used for other providers
- Audit reports will now surface Databricks nodes that should be replaced

### Required Operator Action
- If migrating Databricks workflows, ensure the following are available:
  - A Databricks Personal Access Token (`DATABRICKS_TOKEN`)
  - The Databricks workspace URL (`DATABRICKS_WORKSPACE_URL`)
- Use a current `@ascerta/n8n-nodes-ascerta` release with Databricks node support

---

## 2026-03-04

### Changed
- Documentation cleanup and structure alignment:
  - Simplified root `README.md`
  - Added `docs/COMMAND_REFERENCE.md`
  - Added `docs/LIMITATIONS_AND_KNOWN_ISSUES.md` with customer-safe wording
  - Updated user docs to match current script behavior and flags
  - Expanded fixture documentation
- Moved non-user report artifacts out of repo root into `internal-plans/reports/`

### Operational Impact
- Faster onboarding for operators using the toolkit for the first time
- Lower risk of using outdated command examples
- Clearer separation between customer-facing docs and internal planning docs

### Required Operator Action
- None required.
- Recommended: update any internal runbooks to point to:
  - `docs/GETTING_STARTED.md`
  - `docs/COMMAND_REFERENCE.md`
  - `docs/LIMITATIONS_AND_KNOWN_ISSUES.md`

## 2026-03-02

### Added
- New audit tool: `audit-configure-ascerta-proxy.py`
  - Workflow/provider inventory
  - Credential redirect capability probing
  - Per-node migration manifest with recommended path and confidence
- Enterprise test fixture: `sample-workflow-enterprise-ingest.json`
- Markdown report generation for audits (`--report-format md`)
- JSON-to-Markdown rendering (`--from-json`) for compliance artifact generation

### Changed
- Documentation consolidated into `docs/` (user/customer-facing)

### Operational Impact
- You can now produce two artifacts per audit run:
  - Programmatic JSON report
  - Human/compliance Markdown report
- Migration recommendation quality is improved with credential capability awareness.

### Required Operator Action
- None required for existing scripts.
- Recommended:
  1. Add `audit-configure-ascerta-proxy.py` to pre-migration checks.
  2. Store both `.json` and `.md` audit artifacts for each migration batch.

### Known Limitations
- Some n8n instances do not expose credential detail fields over API, resulting in `unverified` capability status.
- `unverified` credentials should be validated before automated redirect writes.

---

## See Also

- **[Getting Started](./GETTING_STARTED.md)** — Setup and recommended operator flow
- **[Limitations and Known Issues](./LIMITATIONS_AND_KNOWN_ISSUES.md)** — Full list of current constraints
