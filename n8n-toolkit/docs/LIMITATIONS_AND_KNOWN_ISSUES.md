# Limitations and Known Issues

> **[Back to Documentation Index](./README.md)**

This page documents current behavior of `audit-configure-ascerta-proxy.py` so operators can plan migrations with predictable outcomes.

## Scope of Detection

1. The audit tracks only node types explicitly mapped in the script (`NATIVE_NODE_TYPES` and `ASCERTA_NODE_TYPES`).
2. AI calls made through generic nodes (for example `HTTP Request`, `Code`, or custom internal nodes) are not automatically classified as provider usage by this script.
3. Sub-workflow dependencies are not modeled as a graph:
   - each workflow in scope is scanned independently;
   - parent/child relationships (for example `Execute Workflow`) are not annotated in the migration manifest.
4. Expression reference detection is pattern-based and currently looks for `$('NodeName')` and `$("NodeName")` forms inside node parameters.
5. Action signatures are intentionally lightweight and include only a small set of known keys (for example `resource`, `operation`, `model`, `endpoint`).

## Credential Capability and Redirecting

1. Credential redirect capability is a best-effort classification:
   - `likely_supported`
   - `likely_unsupported`
   - `unverified`
   - `not_applicable`
2. On some n8n environments, credential detail fields are not exposed by API (for example HTTP 405 on credential detail endpoints). In those cases, capability is `unverified`.
3. `--configure-credentials` only auto-selects credentials marked `likely_supported`. `unverified` and `likely_unsupported` credentials are not automatically patched.
4. `--configure-credentials` requires live API mode and cannot be combined with `--from-json`.
5. Credential updates are applied one credential at a time and are not transactional. A partial apply can occur if one update fails after earlier updates succeed.

## API and Scale Considerations

1. The workflow listing call is a single `/api/v1/workflows` request. The script does not currently paginate across multiple pages.
2. The script requires API permissions to read workflows and credentials, and to patch credentials when apply mode is used.
3. TLS verification can be disabled with `--insecure` for local/self-signed environments, but this should not be used for production operations.

## Reporting Interpretation

1. Migration manifest paths are recommendations, not execution guarantees.
2. `verify_then_redirect` means additional environment-specific validation is required before write operations.
3. `manual_required` means the script did not identify a deterministic automated migration path from available metadata.

## Operator Guardrails

1. Run read-only audit first and store both JSON and Markdown artifacts.
2. Treat `unverified` credentials as manual review items before apply.
3. Apply changes in batches and validate workflow execution after each batch.
4. Keep rollback options outside the script (for example export credential/workflow backups before patching).

## Provider-Specific Limitations

### Azure OpenAI Services

Azure OpenAI credential redirect is fully supported (the `endpoint` field is rewritten to the Ascerta proxy URL). Node replacement migration is also functional, with the following caveat:

- Azure OpenAI embeddings nodes (`embeddingsAzureOpenAi`) are detected but cannot be migrated automatically. If your workflows use Azure OpenAI embeddings, those nodes require manual reconfiguration after migration.

### AWS Bedrock

Credential redirect is not supported for AWS Bedrock. The standard n8n `aws` credential type uses an IAM Access Key / Secret Key pair, which does not have a URL field that can be swapped to a proxy endpoint.

- Use node replacement (the Ascerta Bedrock Chat Model node) instead of credential redirect.
- Node replacement passthrough requires that the original Bedrock node already has an `aws` credential attached. If the credential is missing from the source node, the migrated Ascerta node will have no AWS credentials and must be configured manually.
- Bedrock embeddings nodes are detected but cannot be migrated automatically.

### Databricks

The Ascerta Databricks node requires an `ascertaDatabricksApi` credential. A native `databricks` credential is not compatible and is not copied to the replacement node. Provide an existing Ascerta Databricks credential or set `ASCERTA_DBX_PAT` and `ASCERTA_DBX_WORKSPACE_URL` so the migrator can create one.

For custom serving endpoints, review **Deployed Model** in the migrated node before running the workflow. The toolkit cannot always determine this value from the source node.

---

## See Also

- **[Getting Started](./GETTING_STARTED.md)** — Recommended operator flow and backup procedures
- **[Audit and Compliance Reports](./AUDIT_AND_REPORTS.md)** — How credential capability states appear in reports
- **[Command Reference](./COMMAND_REFERENCE.md)** — Full flag reference for all scripts
- **[Changelog for Operators](./CHANGELOG_FOR_OPERATORS.md)** — Updates that may resolve or add to known issues
