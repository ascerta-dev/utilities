# Agentic Tool Instructions

Project context for AI coding agents — Claude Code, Codex, Gemini CLI,
Google Antigravity, Cursor, Aider, or any tool that reads a project
file before assisting.

If your tool reads `CLAUDE.md`, `GEMINI.md`, `AGENTS.md`, or similar,
this is the canonical project context. Symlink or copy as needed.

## What this project is

The `n8n-toolkit/` directory (part of the `utilities` repository)
contains Python CLI scripts that audit and migrate
[n8n](https://n8n.io) workflows to route their LLM calls through
[Ascerta](https://ascerta.com) for cost tracking and budget enforcement.

The toolkit pairs with [@ascerta/n8n-nodes-ascerta](https://github.com/ascerta-dev/n8n-nodes-ascerta),
the community node package that exposes Ascerta to n8n workflows.

## Stack

- **Python 3.8+** — tested on 3.10 and 3.12 in CI
- **Standard library only** — no third-party runtime dependencies.
  HTTP via `urllib.request`, JSON via `json`, CLI via `argparse`,
  prompts via `getpass`. Avoid adding `requests`, `httpx`, `pydantic`,
  or any other dep unless there is a hard requirement.
- **pytest** for tests (development only)
- **Bash** for two legacy credential-redirect scripts

## File layout

| Path | Purpose |
|---|---|
| `audit-configure-ascerta-proxy.py` | Read-only audit of n8n workflows. Emits JSON or Markdown reports. Optionally redirects supported credentials to Ascerta. |
| `migrate-workflows-to-ascerta.py` | Interactive migration. Replaces native LLM nodes with Ascerta equivalents, redirects credentials, or both. |
| `migrate-to-ascerta.sh`, `migrate-openai-to-ascerta.sh` | Shell-based credential redirect for OpenAI / Anthropic / Azure OpenAI. Predates the Python tooling; kept for backward compatibility. |
| `test_migrate_workflows.py` | Test suite. Covers both Python scripts. |
| `test-workflow-*.json`, `sample-workflow-*.json` | Workflow fixtures used by tests. |
| `docs/` | User-facing documentation. |
| `.env.example` | Documents required environment variables. |

## How to run things

```bash
# Run the test suite
python3 -m pytest test_migrate_workflows.py -q

# Audit an n8n instance (read-only, no changes)
N8N_BASE_URL=http://localhost:5678 \
N8N_API_KEY=your-n8n-key \
python3 audit-configure-ascerta-proxy.py --out audit.json

# Render a Markdown report from saved JSON
python3 audit-configure-ascerta-proxy.py \
  --from-json audit.json --report-format md --out audit.md

# Migrate workflows (always dry-run first)
N8N_BASE_URL=http://localhost:5678 \
N8N_API_KEY=your-n8n-key \
ASCERTA_BASE_URL=https://api.ascerta.com \
ASCERTA_API_KEY=your-ascerta-key \
python3 migrate-workflows-to-ascerta.py --dry-run

# Apply the migration once dry-run looks correct
python3 migrate-workflows-to-ascerta.py
```

Both scripts honor environment variables and prompt interactively when
they're missing.

## Architecture conventions

These are load-bearing decisions. Don't refactor away without strong
justification.

- **Stdlib only.** Both Python scripts are designed to run on a stock
  Python install with no `pip install` step. New dependencies require
  a deliberate trade-off discussion, not a casual addition.
- **Single-file CLIs.** `audit-configure-ascerta-proxy.py` and
  `migrate-workflows-to-ascerta.py` are intentionally not modularized
  into packages. Each is a self-contained tool.
- **No shared module between the two scripts.** Some logic is
  duplicated (e.g. node type tables) on purpose. Extract a shared
  module only when a third caller needs the same code — not before.
- **Credential passthrough for chat-model replacements.** When the
  migrator replaces a native chat-model node (OpenAI, Anthropic,
  Azure, Bedrock) with the Ascerta equivalent, the existing provider
  credential is copied onto the new node. The user does not re-enter
  API keys. Exception: the Ascerta Databricks node uses
  `ascertaDatabricksApi`, which has no native equivalent and must be
  resolved separately.
- **Source-of-truth dictionaries.** `NATIVE_LLM_NODES` (migrator)
  and `NATIVE_NODE_TYPES` / `ASCERTA_NODE_TYPES` (audit) define
  everything the toolkit understands. Adding support for a new
  upstream node means adding entries to those dicts plus a `build_*`
  function. This is the extension point.

## What an agent should usually do

- **Run the test suite before claiming work is done.** 149 tests
  pass on a clean checkout. New work should add tests, not break
  existing ones. Use `python3 -m pytest test_migrate_workflows.py -q`.
- **Always offer dry-run before write operations.** The migrator's
  `--dry-run` flag exists for a reason. Suggest it before any real
  migration.
- **Read the audit before suggesting a migration.** The audit script
  produces a JSON report with classifications and recommended
  actions per node. That's the right input for a migration plan.
- **Match existing patterns.** The two CLI scripts have established
  conventions for argument parsing, prompting, error handling, and
  output. Follow them rather than introducing a new style.

## What an agent should NOT do

- **Do not add runtime dependencies.** stdlib-only is a project
  invariant. If a task seems to require a third-party library, flag
  it and discuss before adding.
- **Do not add a shared module just to deduplicate two functions.**
  See "no shared module" above.
- **Do not modify `internal-plans/` or `docs/superpowers/`.** These
  paths may exist locally but are gitignored working spaces, not
  shipped artifacts. Treat them as read-only context if present.
- **Do not commit `.env` files with real values.** Only `.env.example`
  ships. All credentials must be `PLACEHOLDER-*` in any committed
  file.
- **Do not run actual (non-dry-run) migrations during development
  or testing** unless the user has explicitly authorized writes
  against the target n8n instance. The migrator modifies workflows
  in place.

## Testing your changes

The test suite uses unittest under pytest. Both Python scripts are
loaded into the test process via `importlib.util.spec_from_file_location`
because their filenames contain hyphens.

Adding a new feature should typically include:

1. A unit test for the smallest piece of logic.
2. A builder test if you added a new node type.
3. An end-to-end test using a JSON workflow fixture.

Running `python3 test_migrate_workflows.py` (no pytest) also works.

## Environment variables

See `.env.example` for the full list. The most common:

| Variable | Purpose |
|---|---|
| `N8N_BASE_URL` | URL of the n8n instance to operate on |
| `N8N_API_KEY` | n8n API key (Settings → API → Create API Key) |
| `ASCERTA_BASE_URL` | Ascerta endpoint, defaults to `https://api.ascerta.com` |
| `ASCERTA_API_KEY` | Ascerta API key |

Provider keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) are only
needed when migrating App-style nodes to Ascerta Proxy. Chat-model
migrations inherit credentials from the source node automatically.

## Related projects

- [@ascerta/n8n-nodes-ascerta](https://github.com/ascerta-dev/n8n-nodes-ascerta) — Ascerta
  community node package. Installed inside the user's n8n instance.
  This toolkit migrates n8n workflows to use those nodes.
- [n8n](https://n8n.io) — the workflow automation platform.
- [Ascerta](https://ascerta.com) — the AI cost management platform this
  toolkit routes workflows through.

## License

MIT. See `LICENSE`.
