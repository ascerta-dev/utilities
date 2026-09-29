# Workflow Fixtures for Testing

> **[Back to Documentation Index](./README.md)**

The repo includes workflow fixtures for testing audit and migration behavior without touching production n8n data. All fixtures are located in the `n8n-toolkit/` directory alongside the migration scripts. Run commands from that directory.

## Included Fixtures

- `sample-workflow-all-providers.json`
  - compact mixed-provider fixture
- `sample-workflow-enterprise-ingest.json`
  - larger enterprise-style fixture with native + Ascerta nodes
- `test-workflow-native-providers.json`
  - native provider-oriented test fixture
- `test-workflow-ascerta-all-providers.json`
  - Ascerta node fixture across providers
- `test-workflow-ascerta-pipeline.json`
  - pipeline/flow-oriented Ascerta fixture

## Recommended Uses

- unit/integration tests for node detection and classification
- dry-run test cases before applying migration changes
- report-rendering consistency checks (`json` vs `md`)
- regression validation when migration logic changes

## Notes

- Fixtures use placeholder IDs and credentials.
- Replace values only when doing environment-specific test runs.

---

## See Also

- **[Audit and Compliance Reports](./AUDIT_AND_REPORTS.md)** — Use fixtures to validate report rendering
- **[Getting Started](./GETTING_STARTED.md)** — Recommended operator flow
