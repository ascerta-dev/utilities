# Software Bill of Materials

## Direct Dependencies

This toolkit uses only the Python standard library. There are no third-party runtime dependencies.

| Package | Version | License | Purpose |
|---------|---------|---------|---------|
| *(none)* | — | — | All imports are Python 3.10+ stdlib |

## Standard Library Modules Used

| Module | Purpose |
|--------|---------|
| `argparse` | CLI argument parsing |
| `copy` | Deep-copying workflow JSON during migration |
| `datetime` | Timestamp generation for reports |
| `getpass` | Secure credential prompting |
| `json` | JSON parsing and serialization |
| `os` | Environment variable access |
| `re` | Expression reference detection |
| `ssl` | TLS context for `--insecure` mode |
| `sys` | Exit codes and stdout/stderr |
| `unittest` | Test framework |
| `urllib.request` / `urllib.error` | HTTP calls to n8n and Ascerta APIs |
| `urllib.parse` | Hostname extraction for Databricks shim detection |

## Dev/Test Dependencies

| Package | Version | License | Purpose |
|---------|---------|---------|---------|
| `pytest` | >=7.0 | MIT | Test framework and runner used in CI |
| `unittest.mock` | stdlib | PSF | Mocking for unit tests |

## Runtime Services

| Service | Provider | Purpose |
|---------|----------|---------|
| n8n REST API | Self-hosted | Workflow and credential read/write |
| Ascerta API | Ascerta | Proxy endpoint for credential redirect |

## Companion Package

| Package | Version | License | Purpose |
|---------|---------|---------|---------|
| [@ascerta/n8n-nodes-ascerta](https://github.com/ascerta-dev/n8n-nodes-ascerta) | >=1.0.0 | MIT | Ascerta community nodes for n8n (required for node replacement strategy) |

Last updated: 2026-05-21
