# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed
- Databricks community-node replacements now attach an
  `ascertaDatabricksApi` credential rather than an incompatible native
  `databricks` credential, and emit resource-locator parameters.

## [1.0.1] - 2026-05-21

### Added
- Databricks-shim detection: `lmChatOpenAi` nodes whose `baseURL` (or
  linked `openAiApi` credential URL) targets a Databricks workspace
  hostname are reclassified as `chat_model_databricks` and migrated to
  `@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks`.
- `--databricks-cloud` and `--databricks-credential-id` CLI flags on
  the migrator for non-interactive Databricks runs.
- `resolve_ascerta_databricks_credential()` helper picks (or creates) a
  `ascertaDatabricksApi` credential once per migration; reused across all
  shim node replacements.
- Audit script recognizes `@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks` and the
  `ascertaDatabricksApi` credential type so workflows already on the new
  Databricks proxy node show up correctly in audit reports.
- `KNOWN_ASCERTA_CREDENTIAL_TYPES` mapping in the audit script tags Ascerta
  credentials with `already_ascerta_credential=true`.
- Test fixtures `test-workflow-databricks-shim.json` and
  `test-workflow-ascerta-databricks.json` plus expanded test coverage
  (shim detection, shim builder, credential resolver, end-to-end
  migration, audit-side recognition).
- Documentation cross-linking and navigation across all user-facing docs
- `SBOM.md` software bill of materials
- `CHANGELOG.md` (this file)

### Changed
- Audit script display labels for Ascerta nodes match upstream
  `@ascerta/n8n-nodes-ascerta` v1.0.1 ("Ascerta OpenAI (Proxy)", "Ascerta Anthropic
  (Proxy)", "Ascerta Azure AI Foundry (Proxy)", "Ascerta Amazon Bedrock
  (Proxy)", "Ascerta Databricks (Proxy)").
- The community-node Databricks builder is now
  `build_ascerta_chat_model_databricks_community_node` to disambiguate
  from the new shim-path builder; dispatch chooses by inspecting
  `databricks_shim` on the discovered node entry.
- Root `README.md` expanded with full documentation table
- `docs/README.md` rewritten as structured documentation hub with reading order
- All doc pages now include navigation headers and "See Also" footers
- `.gitignore` updated to cover standard project artifacts, env files,
  virtualenvs, IDE artifacts, build outputs, and local working directories

## [0.3.0] - 2026-03-06

### Added
- Databricks provider support across migration and audit tooling
- Databricks credential provisioning support
- Test coverage for Databricks detection, node building, credential passthrough (157 tests total)

### Changed
- Documentation updates across getting started guide, command reference, audit reports, and workflow fixtures

## [0.2.0] - 2026-03-04

### Changed
- Documentation cleanup and structure alignment
- Simplified root `README.md`
- Added `docs/COMMAND_REFERENCE.md` and `docs/LIMITATIONS_AND_KNOWN_ISSUES.md`
- Moved non-user report artifacts out of repo root

## [0.1.0] - 2026-03-02

### Added
- Initial release of n8n migration and audit toolkit
- `audit-configure-ascerta-proxy.py` — workflow/provider inventory, credential probing, JSON/Markdown reports
- `migrate-workflows-to-ascerta.py` — interactive migration with strategy selection
- `migrate-to-ascerta.sh` — bulk credential redirect (OpenAI, Anthropic, Azure OpenAI)
- `migrate-openai-to-ascerta.sh` — OpenAI-only credential redirect
- Enterprise test fixture: `sample-workflow-enterprise-ingest.json`
- User documentation in `docs/`
