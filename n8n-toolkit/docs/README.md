# Ascerta n8n Toolkit — Documentation

This documentation covers the Ascerta n8n migration and audit toolkit. It is written for platform operators, integration engineers, and compliance teams working with self-hosted n8n environments.

For the Ascerta n8n community node package itself, see [@ascerta/n8n-nodes-ascerta on GitHub](https://github.com/ascerta-dev/n8n-nodes-ascerta).

---

## Where to Start

If you are new to the toolkit, read the guides in this order:

1. **[Getting Started](./GETTING_STARTED.md)** — Prerequisites, environment setup, and the recommended operator flow from audit through migration.
2. **[Command Reference](./COMMAND_REFERENCE.md)** — Every script, flag, and option. Includes CI/pipeline usage patterns.
3. **[Audit and Compliance Reports](./AUDIT_AND_REPORTS.md)** — How to generate JSON and Markdown audit artifacts, interpret credential capability states, and use apply mode.

## Testing and Validation

4. **[Workflow Fixtures](./WORKFLOW_FIXTURES.md)** — Description of the test workflow files included in this repo and how to use them.

## Reference

5. **[Limitations and Known Issues](./LIMITATIONS_AND_KNOWN_ISSUES.md)** — Current detection scope, credential capability constraints, API limitations, and provider-specific caveats. Read this before any production rollout.
6. **[Changelog for Operators](./CHANGELOG_FOR_OPERATORS.md)** — Release-by-release operational impact, required actions, and known limitations.

---

## Script Overview

| Script | Purpose |
|--------|---------|
| `audit-configure-ascerta-proxy.py` | Workflow inventory, credential capability probing, JSON/Markdown report generation, optional credential patching |
| `migrate-workflows-to-ascerta.py` | Interactive migration with strategy selection: credential redirect, node replacement, or both |
| `migrate-to-ascerta.sh` | Bulk credential redirect for OpenAI, Anthropic, and Azure OpenAI |
| `migrate-openai-to-ascerta.sh` | OpenAI-only credential redirect |

## Intended Audience

- **Platform admins** running self-hosted n8n instances
- **Integration engineers** migrating workflows to route through Ascerta
- **Security and compliance teams** reviewing migration artifacts and audit reports
