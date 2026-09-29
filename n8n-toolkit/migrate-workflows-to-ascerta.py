#!/usr/bin/env python3
"""
migrate-workflows-to-ascerta.py

Scans n8n workflows for native LLM nodes (OpenAI, Anthropic, etc.)
and replaces them with Ascerta Proxy or Ascerta Chat Model nodes.

Requires: Python 3.10+, no pip dependencies (stdlib only).

Environment variables:
  N8N_BASE_URL   - Your n8n instance (e.g. http://localhost:5678)
  N8N_API_KEY    - n8n API key (Settings > API > Create API Key)
  ASCERTA_BASE_URL  - Ascerta instance (e.g. https://api.yourcompany.ascerta.com)
  ASCERTA_API_KEY   - Your Ascerta API key

  Provider API keys are NOT needed for Chat Model migration — the existing
  credentials on each node are automatically passed through to the Ascerta node.

Usage:
  python3 migrate-workflows-to-ascerta.py [OPTIONS]

Options:
  --dry-run       Show what would change without modifying anything
  --auto-yes      Skip per-node confirmation (still prompts for API keys)
  --workflow ID   Migrate only the specified workflow
  --verbose       Show detailed API request/response logging
"""

import argparse
import copy
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# ── ANSI Colors ──────────────────────────────────────────────────────────────

_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(text: str) -> str:
    return _c("1", text)


def dim(text: str) -> str:
    return _c("2", text)


def green(text: str) -> str:
    return _c("32", text)


def yellow(text: str) -> str:
    return _c("33", text)


def red(text: str) -> str:
    return _c("31", text)


def cyan(text: str) -> str:
    return _c("36", text)


# ── Constants ────────────────────────────────────────────────────────────────

# Node type → {provider, replacement_type, feasible, skip_reason}
NATIVE_LLM_NODES = {
    # ── OpenAI ──────────────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatOpenAi": {
        "provider": "openai",
        "replacement": "chat_model",
        "feasible": True,
        "label": "OpenAI Chat Model (LangChain)",
    },
    "@n8n/n8n-nodes-langchain.openai": {
        "provider": "openai",
        "replacement": "proxy",
        "feasible": True,
        "label": "OpenAI (App Node — 16 actions)",
    },
    "@n8n/n8n-nodes-langchain.lmOpenAi": {
        "provider": "openai",
        "replacement": "chat_model",
        "feasible": True,
        "label": "OpenAI Completion Model",
    },
    "@n8n/n8n-nodes-langchain.embeddingsOpenAi": {
        "provider": "openai",
        "replacement": None,
        "feasible": False,
        "label": "OpenAI Embeddings",
        "skip_reason": "Embeddings migration not yet implemented",
    },
    # ── Anthropic ───────────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatAnthropic": {
        "provider": "anthropic",
        "replacement": "chat_model_anthropic",
        "feasible": True,
        "label": "Anthropic Chat Model (LangChain)",
    },
    "@n8n/n8n-nodes-langchain.anthropic": {
        "provider": "anthropic",
        "replacement": "proxy_anthropic",
        "feasible": True,
        "label": "Anthropic (App Node — 10 actions)",
    },
    # ── Azure OpenAI ────────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatAzureOpenAi": {
        "provider": "azureOpenai",
        "replacement": "chat_model_azure",
        "feasible": True,
        "label": "Azure OpenAI Chat Model (LangChain)",
    },
    "@n8n/n8n-nodes-langchain.embeddingsAzureOpenAi": {
        "provider": "azureOpenai",
        "replacement": None,
        "feasible": False,
        "label": "Azure OpenAI Embeddings",
        "skip_reason": "Embeddings migration not yet implemented",
    },
    # ── AWS Bedrock ─────────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatAwsBedrock": {
        "provider": "bedrock",
        "replacement": "chat_model_bedrock",
        "feasible": True,
        "label": "AWS Bedrock Chat Model (LangChain)",
    },
    "@n8n/n8n-nodes-langchain.embeddingsAwsBedrock": {
        "provider": "bedrock",
        "replacement": None,
        "feasible": False,
        "label": "AWS Bedrock Embeddings",
        "skip_reason": "Embeddings migration not yet implemented",
    },
    # ── Google ──────────────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatGoogleGemini": {
        "provider": "google",
        "replacement": None,
        "feasible": False,
        "label": "Google Gemini Chat Model",
        "skip_reason": "Google proxy route not yet available in Ascerta",
    },
    "@n8n/n8n-nodes-langchain.lmChatGoogleVertex": {
        "provider": "google",
        "replacement": None,
        "feasible": False,
        "label": "Google Vertex Chat Model",
        "skip_reason": "Google proxy route not yet available in Ascerta",
    },
    "@n8n/n8n-nodes-langchain.googleGemini": {
        "provider": "google",
        "replacement": None,
        "feasible": False,
        "label": "Google Gemini (App Node)",
        "skip_reason": "Google proxy route not yet available in Ascerta",
    },
    "@n8n/n8n-nodes-langchain.embeddingsGoogleGemini": {
        "provider": "google",
        "replacement": None,
        "feasible": False,
        "label": "Google Gemini Embeddings",
        "skip_reason": "Google proxy route not yet available in Ascerta",
    },
    "@n8n/n8n-nodes-langchain.embeddingsGoogleVertex": {
        "provider": "google",
        "replacement": None,
        "feasible": False,
        "label": "Google Vertex Embeddings",
        "skip_reason": "Google proxy route not yet available in Ascerta",
    },
    # ── Other providers (detected but not yet migratable) ───────────────────
    "@n8n/n8n-nodes-langchain.lmChatMistralCloud": {
        "provider": "mistral",
        "replacement": None,
        "feasible": False,
        "label": "Mistral Chat Model",
        "skip_reason": "Mistral is not a supported Ascerta provider",
    },
    "@n8n/n8n-nodes-langchain.embeddingsMistralCloud": {
        "provider": "mistral",
        "replacement": None,
        "feasible": False,
        "label": "Mistral Embeddings",
        "skip_reason": "Mistral is not a supported Ascerta provider",
    },
    "@n8n/n8n-nodes-langchain.lmChatGroq": {
        "provider": "groq",
        "replacement": None,
        "feasible": False,
        "label": "Groq Chat Model",
        "skip_reason": "Groq is not a supported Ascerta provider",
    },
    "@n8n/n8n-nodes-langchain.lmChatDeepSeek": {
        "provider": "deepseek",
        "replacement": None,
        "feasible": False,
        "label": "DeepSeek Chat Model",
        "skip_reason": "DeepSeek is not a supported Ascerta provider",
    },
    "@n8n/n8n-nodes-langchain.lmChatCohere": {
        "provider": "cohere",
        "replacement": None,
        "feasible": False,
        "label": "Cohere Chat Model",
        "skip_reason": "Cohere is not a supported Ascerta provider",
    },
    "@n8n/n8n-nodes-langchain.embeddingsCohere": {
        "provider": "cohere",
        "replacement": None,
        "feasible": False,
        "label": "Cohere Embeddings",
        "skip_reason": "Cohere is not a supported Ascerta provider",
    },
    "@n8n/n8n-nodes-langchain.lmChatXAiGrok": {
        "provider": "xai",
        "replacement": None,
        "feasible": False,
        "label": "xAI Grok Chat Model",
        "skip_reason": "xAI is not a supported Ascerta provider",
    },
    "@n8n/n8n-nodes-langchain.lmChatOpenRouter": {
        "provider": "openrouter",
        "replacement": None,
        "feasible": False,
        "label": "OpenRouter Chat Model",
        "skip_reason": "OpenRouter is not a supported Ascerta provider",
    },
    "@n8n/n8n-nodes-langchain.lmChatOllama": {
        "provider": "ollama",
        "replacement": None,
        "feasible": False,
        "label": "Ollama Chat Model",
        "skip_reason": "Ollama is a local provider — no proxy needed",
    },
    "@n8n/n8n-nodes-langchain.lmOllama": {
        "provider": "ollama",
        "replacement": None,
        "feasible": False,
        "label": "Ollama Completion Model",
        "skip_reason": "Ollama is a local provider — no proxy needed",
    },
    "@n8n/n8n-nodes-langchain.embeddingsOllama": {
        "provider": "ollama",
        "replacement": None,
        "feasible": False,
        "label": "Ollama Embeddings",
        "skip_reason": "Ollama is a local provider — no proxy needed",
    },
    "@n8n/n8n-nodes-langchain.lmChatVercelAiGateway": {
        "provider": "vercel",
        "replacement": None,
        "feasible": False,
        "label": "Vercel AI Gateway Chat Model",
        "skip_reason": "Vercel AI Gateway is not a supported Ascerta provider",
    },
    "@n8n/n8n-nodes-langchain.lmOpenHuggingFaceInference": {
        "provider": "huggingface",
        "replacement": None,
        "feasible": False,
        "label": "HuggingFace Inference Model",
        "skip_reason": "HuggingFace is not a supported Ascerta provider",
    },
    "@n8n/n8n-nodes-langchain.embeddingsHuggingFaceInference": {
        "provider": "huggingface",
        "replacement": None,
        "feasible": False,
        "label": "HuggingFace Embeddings",
        "skip_reason": "HuggingFace is not a supported Ascerta provider",
    },
    # ── Databricks / AgentBricks ─────────────────────────────────────────────
    # Community node: n8n-nodes-databricks
    "n8n-nodes-databricks.databricks": {
        "provider": "databricks",
        "replacement": "chat_model_databricks",
        "feasible": True,
        "label": "Databricks (Community Node)",
    },
    "n8n-nodes-databricks.lmChatDatabricks": {
        "provider": "databricks",
        "replacement": "chat_model_databricks",
        "feasible": True,
        "label": "Databricks Chat Model (Community Node)",
    },
    "n8n-nodes-databricks.databricksAiAgent": {
        "provider": "databricks",
        "replacement": "chat_model_databricks",
        "feasible": True,
        "label": "Databricks AI Agent (Community Node)",
    },
}

# Provider → env var name for API key
PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azureOpenai": "AZURE_OPENAI_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
    "databricks": "DATABRICKS_TOKEN",
}

# Provider credential config — used by the interactive setup flow.
# Each provider has a list of fields the user needs to supply.
PROVIDER_CREDENTIAL_CONFIG = {
    "openai": {
        "label": "OpenAI",
        "fields": [
            {"key": "apiKey", "prompt": "OpenAI API Key", "env": "OPENAI_API_KEY", "secret": True},
        ],
    },
    "anthropic": {
        "label": "Anthropic",
        "fields": [
            {"key": "apiKey", "prompt": "Anthropic API Key", "env": "ANTHROPIC_API_KEY", "secret": True},
        ],
    },
    "azureOpenai": {
        "label": "Azure OpenAI",
        "fields": [
            {"key": "apiKey", "prompt": "Azure OpenAI API Key", "env": "AZURE_OPENAI_API_KEY", "secret": True},
        ],
    },
    "bedrock": {
        "label": "AWS Bedrock",
        "fields": [
            {"key": "awsAccessKeyId", "prompt": "AWS Access Key ID", "env": "AWS_ACCESS_KEY_ID", "secret": True},
            {"key": "awsSecretAccessKey", "prompt": "AWS Secret Access Key", "env": "AWS_SECRET_ACCESS_KEY", "secret": True},
            {"key": "awsRegion", "prompt": "AWS Region", "env": "AWS_REGION", "default": "us-east-1", "secret": False},
        ],
    },
    "databricks": {
        "label": "Databricks",
        "fields": [
            {"key": "token", "prompt": "Databricks Personal Access Token", "env": "DATABRICKS_TOKEN", "secret": True},
            {"key": "host", "prompt": "Databricks Workspace URL", "env": "DATABRICKS_WORKSPACE_URL", "secret": False},
        ],
    },
}

# Fields accepted by PUT /api/v1/workflows/{id}.
# Using an allowlist is safer than a denylist — n8n adds new read-only fields
# across versions and the PUT endpoint rejects anything it doesn't recognize.
WORKFLOW_PUT_ALLOWED_FIELDS = {
    "name", "nodes", "connections", "settings",
}


# ── API Client ───────────────────────────────────────────────────────────────

class N8nApiClient:
    def __init__(self, base_url: str, api_key: str, verbose: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.verbose = verbose

    def _request(self, method: str, path: str, body: dict = None, quiet: bool = False) -> dict:
        url = f"{self.base_url}{path}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-N8N-API-KEY", self.api_key)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        if self.verbose:
            print(f"  {dim('[API]')} {method} {url}")
            if body:
                redacted = _redact_dict(body)
                print(f"  {dim('[API]')} Body: {json.dumps(redacted, indent=2)[:500]}")

        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read().decode("utf-8")
                if self.verbose:
                    preview = resp_body[:500]
                    if len(resp_body) > 500:
                        preview += "...(truncated)"
                    print(f"  {dim('[API]')} {resp.status} OK — {preview}")
                return json.loads(resp_body) if resp_body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if not quiet:
                print(f"  {red('ERROR')}: {method} {path} -> HTTP {e.code}")
                print(f"  {err_body[:500]}")
            raise SystemExit(1)

    def get(self, path: str, quiet: bool = False) -> dict:
        return self._request("GET", path, quiet=quiet)

    def post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, body)

    def put(self, path: str, body: dict) -> dict:
        return self._request("PUT", path, body)

    def patch(self, path: str, body: dict) -> dict:
        return self._request("PATCH", path, body)


def _redact_dict(d: dict) -> dict:
    """Shallow copy with sensitive-looking values masked."""
    sensitive = {"apikey", "api_key", "providerApiKey", "secret", "password", "token", "headervalue"}
    out = {}
    for k, v in d.items():
        if k.lower().replace("-", "").replace("_", "") in {s.lower().replace("_", "") for s in sensitive}:
            out[k] = "****"
        elif isinstance(v, dict):
            out[k] = _redact_dict(v)
        else:
            out[k] = v
    return out


# ── Interactive Prompts ───────────────────────────────────────────────────────

def _is_interactive() -> bool:
    """Return True if stdin is a terminal (not piped)."""
    return hasattr(sys.stdin, "isatty") and sys.stdin.isatty()


def prompt_value(label: str, env_var: str = None, default: str = None, secret: bool = False) -> str:
    """Prompt the user for a value, with optional env-var default."""
    env_val = os.environ.get(env_var, "").strip() if env_var else ""
    if env_val:
        masked = env_val[:4] + "****" if secret and len(env_val) > 4 else env_val
        print(f"  {green('Found')} {env_var} in environment ({masked})")
        return env_val

    hint = f" [{default}]" if default else ""
    if secret:
        val = getpass.getpass(f"  {label}{hint}: ").strip()
    else:
        val = input(f"  {label}{hint}: ").strip()

    return val if val else (default or "")


def setup_connection_details(args) -> dict:
    """Interactively gather connection details, using env vars as defaults."""
    print(bold("  Connection Setup"))
    print()

    n8n_base = prompt_value("n8n Instance URL", "N8N_BASE_URL", "http://localhost:5678")
    if not n8n_base:
        print(f"  {red('ERROR')}: n8n URL is required")
        raise SystemExit(1)

    n8n_key = prompt_value("n8n API Key", "N8N_API_KEY", secret=True)
    if not n8n_key:
        print(f"  {red('ERROR')}: n8n API key is required")
        raise SystemExit(1)

    print()
    ascerta_base = prompt_value("Ascerta Base URL", "ASCERTA_BASE_URL", "https://api.ascerta.com")
    if not ascerta_base:
        print(f"  {red('ERROR')}: Ascerta URL is required")
        raise SystemExit(1)

    ascerta_key = prompt_value("Ascerta API Key", "ASCERTA_API_KEY", secret=True)
    if not ascerta_key:
        print(f"  {red('ERROR')}: Ascerta API key is required")
        raise SystemExit(1)

    return {
        "n8n_base": n8n_base.rstrip("/"),
        "n8n_key": n8n_key,
        "ascerta_base": ascerta_base.rstrip("/"),
        "ascerta_key": ascerta_key,
    }


def collect_provider_credentials(found_nodes: list) -> dict:
    """Interactively collect credentials for each detected provider.

    Returns {provider: cred_value} where cred_value is either a string (API key)
    or a dict (for providers needing multiple fields like Bedrock).
    """
    needed = set()
    for n in found_nodes:
        if n["feasible"]:
            needed.add(n["provider"])

    if not needed:
        return {}

    print(bold("  Provider API Keys"))
    print()

    creds = {}
    for provider in sorted(needed):
        config = PROVIDER_CREDENTIAL_CONFIG.get(provider)
        if not config:
            continue

        fields = config["fields"]
        if len(fields) == 1:
            # Simple single-key provider
            f = fields[0]
            val = prompt_value(f["prompt"], f.get("env"), f.get("default"), f.get("secret", True))
            if val:
                creds[provider] = val
            else:
                print(f"  {yellow('WARNING')}: No key for {config['label']} — those nodes will be skipped")
        else:
            # Multi-field provider (e.g. Bedrock)
            print(f"  {bold(config['label'])} credentials:")
            provider_creds = {}
            missing = False
            for f in fields:
                val = prompt_value(f"  {f['prompt']}", f.get("env"), f.get("default"), f.get("secret", True))
                if val:
                    provider_creds[f["key"]] = val
                elif not f.get("default"):
                    missing = True
            if missing:
                print(f"  {yellow('WARNING')}: Incomplete credentials for {config['label']} — those nodes will be skipped")
            else:
                creds[provider] = provider_creds

    return creds


# ── Databricks Shim Detection ────────────────────────────────────────────────

DATABRICKS_HOSTNAME_SUFFIXES = {
    ".azuredatabricks.net": "azure",
    ".cloud.databricks.com": "aws",  # default — overridable per spec §4.2
}


def _classify_databricks_hostname(url):
    """Return cloud_provider for a Databricks workspace hostname, or None."""
    if not url or not isinstance(url, str):
        return None
    try:
        parts = urllib.parse.urlsplit(url)
    except (ValueError, AttributeError):
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    for suffix, cloud in DATABRICKS_HOSTNAME_SUFFIXES.items():
        if host.endswith(suffix):
            return cloud
    return None


def classify_databricks_shim(node: dict, client) -> dict:
    """Classify whether an lmChatOpenAi node is actually a Databricks shim.

    Inspects parameters.options.baseURL first, then falls back to the
    linked openAiApi credential's data.url (if a client is supplied).

    Returns: {"detected": bool, "cloud_provider": str|None, "source": str}
    where source is one of "node_param", "credential", "none".
    """
    params = node.get("parameters", {}) or {}
    options = params.get("options", {}) or {}
    base_url = options.get("baseURL") if isinstance(options, dict) else None

    cloud = _classify_databricks_hostname(base_url) if base_url else None
    if cloud:
        return {"detected": True, "cloud_provider": cloud, "source": "node_param"}

    # Fall back to credential lookup
    if client is not None:
        creds = node.get("credentials", {}) or {}
        oai = creds.get("openAiApi") if isinstance(creds, dict) else None
        cred_id = oai.get("id") if isinstance(oai, dict) else None
        if cred_id:
            data = _fetch_credential_data(client, cred_id) or {}
            cred_url = data.get("url") if isinstance(data, dict) else None
            cloud = _classify_databricks_hostname(cred_url) if cred_url else None
            if cloud:
                return {"detected": True, "cloud_provider": cloud, "source": "credential"}

    return {"detected": False, "cloud_provider": None, "source": "none"}


# ── Node Detection ───────────────────────────────────────────────────────────

def find_llm_nodes(workflows: list, client=None) -> list:
    """Scan workflows and return a list of found LLM node descriptors.

    When client is provided, lmChatOpenAi nodes are checked for
    Databricks workspace baseURLs and reclassified as
    chat_model_databricks shims when detected.
    """
    results = []
    for wf in workflows:
        wf_id = wf.get("id", "?")
        wf_name = wf.get("name", "Untitled")
        for node in wf.get("nodes", []):
            node_type = node.get("type", "")
            if node_type not in NATIVE_LLM_NODES:
                continue
            info = dict(NATIVE_LLM_NODES[node_type])

            # lmChatOpenAi may actually be a Databricks shim — reclassify.
            if node_type == "@n8n/n8n-nodes-langchain.lmChatOpenAi":
                shim = classify_databricks_shim(node, client=client)
                if shim["detected"]:
                    info["replacement"] = "chat_model_databricks"
                    info["label"] = "Databricks-via-OpenAI Shim"
                    entry = {
                        "workflow_id": wf_id,
                        "workflow_name": wf_name,
                        "node": node,
                        "node_type": node_type,
                        "databricks_shim": shim,
                        **info,
                    }
                    results.append(entry)
                    continue

            results.append({
                "workflow_id": wf_id,
                "workflow_name": wf_name,
                "node": node,
                "node_type": node_type,
                **info,
            })
    return results


# Databricks URL patterns matched in HTTP Request node parameters
_DATABRICKS_URL_PATTERNS = [
    ".databricks.com/serving-endpoints/",
    ".databricks.com/api/2.0/serving-endpoints/",
    ".databricks.com/api/v1/",
    ".databricksapps.com/",
]


def find_databricks_nodes(workflows: list) -> list:
    """Detect Databricks/AgentBricks nodes not already in NATIVE_LLM_NODES.

    Two detection patterns:
      1. Any node whose type contains 'databricks' (case-insensitive) that
         isn't already in NATIVE_LLM_NODES (those are caught by find_llm_nodes).
      2. HTTP Request nodes whose URL parameters target Databricks endpoints.

    Returns a list of descriptors with workflow context and detection reason.
    """
    results = []
    for wf in workflows:
        wf_id = wf.get("id", "?")
        wf_name = wf.get("name", "Untitled")
        for node in wf.get("nodes", []):
            node_type = node.get("type", "")
            node_name = node.get("name", "?")
            pos = node.get("position", [0, 0])

            # Pattern 1: Community node with 'databricks' in type
            if "databricks" in node_type.lower() and node_type not in NATIVE_LLM_NODES:
                results.append({
                    "workflow_id": wf_id,
                    "workflow_name": wf_name,
                    "node_name": node_name,
                    "node_type": node_type,
                    "position": pos,
                    "reason": "Databricks community node",
                })
                continue

            # Pattern 2: HTTP Request nodes calling Databricks URLs
            if node_type in (
                "n8n-nodes-base.httpRequest",
                "@n8n/n8n-nodes-langchain.toolHttpRequest",
            ):
                params = node.get("parameters", {})
                url = params.get("url", "")
                # Also check if URL is in an expression
                if isinstance(url, dict):
                    url = str(url.get("value", ""))
                url_lower = url.lower()
                for pattern in _DATABRICKS_URL_PATTERNS:
                    if pattern in url_lower:
                        results.append({
                            "workflow_id": wf_id,
                            "workflow_name": wf_name,
                            "node_name": node_name,
                            "node_type": node_type,
                            "position": pos,
                            "reason": f"HTTP Request to Databricks ({pattern.strip('/')})",
                        })
                        break

    return results


# ── Credential Management ────────────────────────────────────────────────────

def ensure_ascerta_credential(client: N8nApiClient, ascerta_api_key: str, ascerta_base_url: str) -> dict:
    """Find or create a ascertaApi credential in n8n. Returns {id, name}."""
    print(f"  Checking for Ascerta credential in n8n...")

    creds_resp = client.get("/api/v1/credentials")
    creds = creds_resp.get("data", creds_resp) if isinstance(creds_resp, dict) else creds_resp
    if isinstance(creds, dict) and "data" not in creds:
        # Some n8n versions return a list directly
        creds = [creds_resp] if creds_resp.get("type") else []

    for c in creds:
        if c.get("type") == "ascertaApi":
            print(f'  {green("Found")} Ascerta credential: "{c["name"]}" (ID: {c["id"]})')
            return {"id": c["id"], "name": c["name"]}

    print(f"  No Ascerta credential found — creating one...")
    new_cred = client.post("/api/v1/credentials", {
        "name": "Ascerta API",
        "type": "ascertaApi",
        "data": {
            "apiKey": ascerta_api_key,
            "baseUrl": ascerta_base_url,
        },
    })
    cred_id = new_cred.get("id", "?")
    print(f'  {green("Created")} Ascerta credential: "Ascerta API" (ID: {cred_id})')
    return {"id": cred_id, "name": "Ascerta API"}


def resolve_ascerta_databricks_credential(client: N8nApiClient, args, dry_run: bool):
    """Resolve a ascertaDatabricksApi credential for the migration run.

    Returns {"id", "name"} or None. Runs once per migration; the result
    is reused across all Databricks-shim node replacements.
    """
    if dry_run:
        return {"id": "dry-run-dbx", "name": "Ascerta Databricks (dry run)"}

    # Explicit ID flag wins
    explicit_id = getattr(args, "databricks_credential_id", None)
    if explicit_id:
        cred = client.get(f"/api/v1/credentials/{explicit_id}")
        # n8n may return the credential wrapped as {"data": {...}} on some
        # versions — unwrap before the type check.
        if isinstance(cred, dict) and "type" not in cred and isinstance(cred.get("data"), dict):
            cred = cred["data"]
        if cred.get("type") != "ascertaDatabricksApi":
            print(f"  {red('ERROR')}: --databricks-credential-id {explicit_id} "
                  f"has type {cred.get('type')!r}, expected 'ascertaDatabricksApi'")
            raise SystemExit(1)
        print(f'  {green("Using")} pinned Databricks credential "{cred.get("name", "?")}" '
              f'(ID: {explicit_id})')
        return {"id": str(explicit_id), "name": cred.get("name", "Databricks")}

    # Discover existing
    creds_resp = client.get("/api/v1/credentials")
    all_creds = creds_resp.get("data", creds_resp) if isinstance(creds_resp, dict) else creds_resp
    if isinstance(all_creds, dict):
        all_creds = [all_creds]
    dbx_creds = [c for c in (all_creds or []) if c.get("type") == "ascertaDatabricksApi"]

    if len(dbx_creds) == 1:
        c = dbx_creds[0]
        print(f'  {green("Found")} Databricks credential "{c["name"]}" (ID: {c["id"]})')
        return {"id": str(c["id"]), "name": c["name"]}

    if len(dbx_creds) >= 2:
        if getattr(args, "auto_yes", False) or not _is_interactive():
            c = dbx_creds[0]
            print(f'  {yellow("Multiple Databricks credentials found")} — '
                  f'using "{c["name"]}" (ID: {c["id"]}). '
                  f'Pass --databricks-credential-id to pick a different one.')
            return {"id": str(c["id"]), "name": c["name"]}
        print(f"  {bold('Multiple Databricks credentials found:')}")
        for i, c in enumerate(dbx_creds, 1):
            print(f"    [{i}] {c['name']} (ID: {c['id']})")
        answer = input(f"  Pick one [1-{len(dbx_creds)}]: ").strip()
        try:
            idx = int(answer) - 1
            if idx < 0 or idx >= len(dbx_creds):
                raise IndexError("out of range")
            c = dbx_creds[idx]
            return {"id": str(c["id"]), "name": c["name"]}
        except (ValueError, IndexError):
            print(f"  {yellow('Invalid selection')} — using first ({dbx_creds[0]['name']})")
            c = dbx_creds[0]
            return {"id": str(c["id"]), "name": c["name"]}

    # 0 found — try env vars or prompt
    pat = os.environ.get("ASCERTA_DBX_PAT", "").strip()
    workspace_url = os.environ.get("ASCERTA_DBX_WORKSPACE_URL", "").strip()
    auto = getattr(args, "auto_yes", False) or not _is_interactive()

    if (not pat or not workspace_url) and auto:
        print(f"  {yellow('No ascertaDatabricksApi credential found')}; "
              f"set both ASCERTA_DBX_PAT and ASCERTA_DBX_WORKSPACE_URL to "
              f"auto-create, or run interactively. Databricks nodes will be "
              f"migrated without their credential — wire it up manually after.")
        return None

    if not pat or not workspace_url:
        print(f"  {bold('No Databricks credential found — creating one')}")
        if not pat:
            pat = prompt_value("Databricks Personal Access Token", "ASCERTA_DBX_PAT", secret=True)
        if not workspace_url:
            workspace_url = prompt_value("Databricks Workspace URL", "ASCERTA_DBX_WORKSPACE_URL")
        if not pat or not workspace_url:
            print(f"  {yellow('Skipping credential creation — missing PAT or workspace URL')}")
            return None

    new_cred = client.post("/api/v1/credentials", {
        "name": "Ascerta Databricks API",
        "type": "ascertaDatabricksApi",
        "data": {
            "accessToken": pat,
            "workspaceUrl": workspace_url,
        },
    })
    cred_id = new_cred.get("id", "?")
    print(f'  {green("Created")} Databricks credential "Ascerta Databricks API" (ID: {cred_id})')
    return {"id": str(cred_id), "name": new_cred.get("name", "Ascerta Databricks API")}


# ── Provider API Key Collection ──────────────────────────────────────────────

def collect_provider_keys(found_nodes: list) -> dict:
    """Legacy wrapper — delegates to collect_provider_credentials."""
    return collect_provider_credentials(found_nodes)


# ── Node Builders ────────────────────────────────────────────────────────────

def _extract_native_credential(original: dict, cred_type: str) -> dict:
    """Extract an existing credential reference from the original node.

    Returns a dict like {"id": "xxx", "name": "OpenAI account"} or {} if not found.
    """
    creds = original.get("credentials", {}) or {}
    for key, val in creds.items():
        if key == cred_type and isinstance(val, dict) and val.get("id"):
            return val
    return {}


# Maps replacement type → native credential key that the Ascerta node should inherit.
NATIVE_CREDENTIAL_KEY = {
    "chat_model": "openAiApi",
    "chat_model_anthropic": "anthropicApi",
    "chat_model_azure": "azureOpenAiApi",
    "chat_model_bedrock": "aws",
    "chat_model_databricks": "databricks",
    "proxy": "openAiApi",
    "proxy_anthropic": "anthropicApi",
}


def build_ascerta_chat_model_node(
    original: dict,
    ascerta_cred: dict,
    provider_key: str,
    new_name: str,
) -> dict:
    """Build a Ascerta Chat Model node from a native OpenAI LangChain chat model."""
    params = original.get("parameters", {})

    # Extract model — newer n8n versions (2.x) store this as a resourceLocator
    # object {"mode": "list", "value": "gpt-4o"} instead of a plain string.
    model = params.get("model", "gpt-4o")
    if isinstance(model, dict):
        model = model.get("value", "gpt-4o")

    # Extract options from native node
    native_options = params.get("options", {})
    options = {}
    for key in ("temperature", "maxTokens", "topP", "frequencyPenalty", "presencePenalty", "timeout", "maxRetries"):
        if key in native_options:
            options[key] = native_options[key]

    # Pass through the existing OpenAI credential — no need to re-enter API keys
    native_cred = _extract_native_credential(original, "openAiApi")

    credentials = {
        "ascertaApi": {
            "id": str(ascerta_cred["id"]),
            "name": ascerta_cred["name"],
        },
    }
    if native_cred:
        credentials["openAiApi"] = native_cred

    new_node = {
        "id": original.get("id", ""),
        "name": new_name,
        "type": "@ascerta/n8n-nodes-ascerta.lmChatAscerta",
        "typeVersion": 1,
        "position": original.get("position", [0, 0]),
        "parameters": {
            "model": model,
            "options": options,
            # Tracking defaults
            "useCaseName": "={{ $workflow.name.replaceAll(' ', '-') }}",
            "useCaseId": "={{ 'openai/' + $parameter.model + '/' + $execution.id }}",
            "useCaseStep": "={{ $node.name }}",
        },
        "credentials": credentials,
    }
    return new_node


def build_ascerta_chat_model_anthropic_node(
    original: dict,
    ascerta_cred: dict,
    provider_key: str,
    new_name: str,
) -> dict:
    """Build a Ascerta Anthropic Chat Model node from a native Anthropic LangChain chat model."""
    params = original.get("parameters", {})

    # Native n8n Anthropic node uses "modelName" in some versions, "model" in others
    model = params.get("model", params.get("modelName", ""))
    if isinstance(model, dict):
        model = model.get("value", "")

    native_options = params.get("options", {})
    options = {}
    for key in ("maxTokensToSample", "temperature", "topK", "topP", "thinking", "thinkingBudget"):
        if key in native_options:
            options[key] = native_options[key]

    # Pass through the existing Anthropic credential
    native_cred = _extract_native_credential(original, "anthropicApi")

    credentials = {
        "ascertaApi": {
            "id": str(ascerta_cred["id"]),
            "name": ascerta_cred["name"],
        },
    }
    if native_cred:
        credentials["anthropicApi"] = native_cred

    new_node = {
        "id": original.get("id", ""),
        "name": new_name,
        "type": "@ascerta/n8n-nodes-ascerta.lmChatAscertaAnthropic",
        "typeVersion": 1,
        "position": original.get("position", [0, 0]),
        "parameters": {
            "model": model,
            "options": options,
            "useCaseName": "={{ $workflow.name.replaceAll(' ', '-') }}",
            "useCaseId": "={{ 'anthropic/' + $parameter.model + '/' + $execution.id }}",
            "useCaseStep": "={{ $node.name }}",
        },
        "credentials": credentials,
    }
    return new_node


def build_ascerta_chat_model_azure_node(
    original: dict,
    ascerta_cred: dict,
    provider_key: str,
    new_name: str,
) -> dict:
    """Build a Ascerta Azure OpenAI Chat Model node from a native Azure OpenAI LangChain chat model."""
    params = original.get("parameters", {})

    # Azure uses deployment name instead of model
    deployment = params.get("model", "")
    if isinstance(deployment, dict):
        deployment = deployment.get("value", "")

    api_version = params.get("apiVersion", "2024-08-01-preview")

    # Extract options
    native_options = params.get("options", {})
    options = {}
    for key in ("temperature", "maxTokens", "topP", "frequencyPenalty", "presencePenalty", "timeout", "maxRetries"):
        if key in native_options:
            options[key] = native_options[key]

    # Pass through the existing Azure OpenAI credential
    native_cred = _extract_native_credential(original, "azureOpenAiApi")

    credentials = {
        "ascertaApi": {
            "id": str(ascerta_cred["id"]),
            "name": ascerta_cred["name"],
        },
    }
    if native_cred:
        credentials["azureOpenAiApi"] = native_cred

    new_node = {
        "id": original.get("id", ""),
        "name": new_name,
        "type": "@ascerta/n8n-nodes-ascerta.lmChatAscertaAzure",
        "typeVersion": 1,
        "position": original.get("position", [0, 0]),
        "parameters": {
            "deploymentName": deployment,
            "apiVersion": api_version,
            "options": options,
            "useCaseName": "={{ $workflow.name.replaceAll(' ', '-') }}",
            "useCaseId": "={{ 'azure/' + $parameter.deploymentName + '/' + $execution.id }}",
            "useCaseStep": "={{ $node.name }}",
        },
        "credentials": credentials,
    }
    return new_node


def build_ascerta_chat_model_bedrock_node(
    original: dict,
    ascerta_cred: dict,
    provider_key: str,
    new_name: str,
) -> dict:
    """Build a Ascerta Bedrock Chat Model node from a native AWS Bedrock LangChain chat model."""
    params = original.get("parameters", {})

    model = params.get("model", "")
    if isinstance(model, dict):
        model = model.get("value", "")

    region = params.get("region", "us-east-1")

    native_options = params.get("options", {})
    options = {}
    for key in ("temperature", "maxTokens", "topP"):
        if key in native_options:
            options[key] = native_options[key]

    # Pass through the existing AWS credential
    native_cred = _extract_native_credential(original, "aws")

    credentials = {
        "ascertaApi": {
            "id": str(ascerta_cred["id"]),
            "name": ascerta_cred["name"],
        },
    }
    if native_cred:
        credentials["aws"] = native_cred

    new_node = {
        "id": original.get("id", ""),
        "name": new_name,
        "type": "@ascerta/n8n-nodes-ascerta.lmChatAscertaBedrock",
        "typeVersion": 1,
        "position": original.get("position", [0, 0]),
        "parameters": {
            "model": model,
            "region": region,
            "options": options,
            "useCaseName": "={{ $workflow.name.replaceAll(' ', '-') }}",
            "useCaseId": "={{ 'bedrock/' + $parameter.model + '/' + $execution.id }}",
            "useCaseStep": "={{ $node.name }}",
        },
        "credentials": credentials,
    }
    return new_node


def build_ascerta_chat_model_databricks_community_node(
    original: dict,
    ascerta_cred: dict,
    provider_key: str,
    new_name: str,
    cloud_provider: str = "aws",
    dbx_cred=None,
) -> dict:
    """Build a Ascerta Databricks Chat Model node from a Databricks community node.

    cloud_provider defaults to ``aws``. Pass an explicit value (typically the
    ``--databricks-cloud`` CLI flag) when the workspace runs on Azure, GCP, or
    a self-hosted Databricks deployment.
    """
    params = original.get("parameters", {})

    # Extract endpoint name — community node may use "endpoint", "model", or "endpointName"
    endpoint = params.get("endpoint", params.get("endpointName", params.get("model", "")))
    if isinstance(endpoint, dict):
        endpoint = endpoint.get("value", "")
    deployed_model = params.get("deployedModel", "")
    if isinstance(deployed_model, dict):
        deployed_model = deployed_model.get("value", "")

    # cloud_provider was supplied by the caller (defaults to "aws"). Community
    # Databricks nodes don't carry a workspace hostname, so the dispatcher
    # passes through the --databricks-cloud CLI flag (or "aws" by default).

    native_options = params.get("options", {})
    options = {}
    for key in ("temperature", "maxTokens", "topP", "frequencyPenalty", "presencePenalty"):
        if key in native_options:
            options[key] = native_options[key]

    credentials = {
        "ascertaApi": {
            "id": str(ascerta_cred["id"]),
            "name": ascerta_cred["name"],
        },
    }
    # The Ascerta node requires its own credential type; a generic
    # n8n-nodes-databricks credential cannot be attached to it.
    if dbx_cred:
        credentials["ascertaDatabricksApi"] = {
            "id": str(dbx_cred["id"]), "name": dbx_cred["name"],
        }

    new_node = {
        "id": original.get("id", ""),
        "name": new_name,
        "type": "@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks",
        "typeVersion": 1,
        "position": original.get("position", [0, 0]),
        "parameters": {
            "endpointName": {"mode": "name", "value": endpoint},
            "deployedModel": {"mode": "name", "value": deployed_model},
            "cloudProvider": cloud_provider,
            "options": options,
            "useCaseName": "={{ $workflow.name.replaceAll(' ', '-') }}",
            "useCaseId": "={{ 'databricks/' + $parameter.endpointName + '/' + $execution.id }}",
            "useCaseStep": "={{ $node.name }}",
        },
        "credentials": credentials,
    }
    return new_node


def build_ascerta_chat_model_databricks_node(
    original: dict,
    ascerta_cred: dict,
    dbx_cred,
    cloud_provider: str,
    new_name: str,
) -> dict:
    """Build a Ascerta Databricks Chat Model node from a Databricks-shim
    OpenAI LangChain chat model. dbx_cred may be None when the user has
    no ascertaDatabricksApi credential; the node ships without it and must
    be wired up manually in the n8n UI."""
    params = original.get("parameters", {})

    model = params.get("model", "")
    if isinstance(model, dict):
        model = model.get("value", "")

    native_options = params.get("options", {}) or {}
    options = {
        k: native_options[k]
        for k in (
            "temperature", "maxTokens", "topP",
            "frequencyPenalty", "presencePenalty",
        )
        if k in native_options
    }

    credentials = {
        "ascertaApi": {"id": str(ascerta_cred["id"]), "name": ascerta_cred["name"]},
    }
    if dbx_cred:
        credentials["ascertaDatabricksApi"] = {
            "id": str(dbx_cred["id"]),
            "name": dbx_cred["name"],
        }

    return {
        "id": original.get("id", ""),
        "name": new_name,
        "type": "@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks",
        "typeVersion": 1,
        "position": original.get("position", [0, 0]),
        "parameters": {
            "endpointName": {"mode": "name", "value": model},
            "deployedModel": {"mode": "name", "value": ""},
            "cloudProvider": cloud_provider,
            "options": options,
            "useCaseName": "={{ $workflow.name.replaceAll(' ', '-') }}",
            "useCaseId": "={{ 'databricks/' + $parameter.endpointName.value + '/' + $execution.id }}",
            "useCaseStep": "={{ $node.name }}",
        },
        "credentials": credentials,
    }


def build_ascerta_proxy_anthropic_node(
    original: dict,
    ascerta_cred: dict,
    provider_key: str,
    new_name: str,
) -> dict:
    """Build a Ascerta Proxy node from a native Anthropic app node."""
    params = original.get("parameters", {})

    model = params.get("model", "claude-sonnet-4-20250514")
    if isinstance(model, dict):
        model = model.get("value", "claude-sonnet-4-20250514")

    # Try to extract the user message content
    text = params.get("text", params.get("prompt", ""))
    if not text:
        text = "Hello!"
    messages = json.dumps([{"role": "user", "content": text}])

    new_node = {
        "id": original.get("id", ""),
        "name": new_name,
        "type": "@ascerta/n8n-nodes-ascerta.ascerta",
        "typeVersion": 1,
        "position": original.get("position", [0, 0]),
        "parameters": {
            "provider": "anthropic",
            "providerApiKey": provider_key,
            "model": model,
            "messages": messages,
            # Tracking defaults
            "useCaseName": "={{ $workflow.name.replaceAll(' ', '-') }}",
            "useCaseId": "={{ 'anthropic/' + $parameter.model + '/' + $execution.id }}",
            "useCaseStep": "={{ $node.name }}",
            "includeCostData": True,
            "returnFullResponse": False,
            "debugLogging": False,
        },
        "credentials": {
            "ascertaApi": {
                "id": str(ascerta_cred["id"]),
                "name": ascerta_cred["name"],
            },
        },
    }
    return new_node


# ── Credential Redirect ──────────────────────────────────────────────────────

# Credential types that support URL redirect (base URL swap to Ascerta proxy).
# This is the simplest migration: change the URL field, route ALL actions through Ascerta.
CREDENTIAL_REDIRECT_CONFIG = {
    "openAiApi": {
        "provider": "openai",
        "url_field": "url",
        "proxy_path": "/api/v1/proxy/openai/v1",
        "header_field": "xProxy-api-key",  # Ascerta key sent as custom header alongside Bearer token
    },
    "anthropicApi": {
        "provider": "anthropic",
        "url_field": "url",
        "proxy_path": "/api/v1/proxy/anthropic",
        "header_field": "xProxy-api-key",  # Ascerta key sent as custom header
    },
    "azureOpenAiApi": {
        "provider": "azureOpenai",
        "url_field": "endpoint",
        "proxy_path": "/api/v1/proxy/azure.openai",
        "header_field": "xProxy-api-key",  # Ascerta key sent as custom header
    },
}


def _fetch_credential_data(client, cred_id: str) -> dict:
    """Fetch existing (decrypted) credential data from n8n.

    Uses the ``?includeData=true`` query parameter supported by n8n v1.x+.
    Returns the ``data`` dict if available, or an empty dict on failure.
    """
    try:
        resp = client.get(f"/api/v1/credentials/{cred_id}?includeData=true", quiet=True)
        return resp.get("data", {}) or {}
    except SystemExit:
        return {}


def build_credential_patch(cred_type: str, ascerta_base_url: str, ascerta_api_key: str,
                           existing_data: dict = None) -> dict:
    """Build the PATCH body to redirect a credential to Ascerta proxy.

    When *existing_data* is provided (fetched from n8n), the redirect fields are
    merged into the full credential data so n8n's PATCH validation passes.
    Without existing_data, only the redirect fields are returned (may fail on n8n
    versions that require all fields in a PATCH).
    """
    config = CREDENTIAL_REDIRECT_CONFIG.get(cred_type)
    if not config:
        return {}

    base = ascerta_base_url.rstrip("/")
    proxy_url = f"{base}{config['proxy_path']}"

    # Start from existing data if available, otherwise from scratch
    data = dict(existing_data) if existing_data else {}

    # Apply redirect changes
    data[config["url_field"]] = proxy_url
    if config.get("header_field"):
        data["headerName"] = config["header_field"]
        data["headerValue"] = ascerta_api_key

    return {"data": data}


def find_redirectable_credentials(client, workflows: list) -> list:
    """Find all credentials used by AI nodes that can be redirected."""
    # Collect credential IDs from detected AI nodes
    cred_ids = set()
    for wf in workflows:
        for node in wf.get("nodes", []):
            node_type = node.get("type", "")
            if node_type in NATIVE_LLM_NODES:
                for cred_key, cred_info in (node.get("credentials", {}) or {}).items():
                    if isinstance(cred_info, dict) and cred_info.get("id"):
                        cred_ids.add((str(cred_info["id"]), cred_key))

    # Fetch credential metadata to get their types
    if not cred_ids:
        return []

    creds_resp = client.get("/api/v1/credentials")
    all_creds = creds_resp.get("data", creds_resp) if isinstance(creds_resp, dict) else creds_resp
    if isinstance(all_creds, dict):
        all_creds = [all_creds]

    by_id = {str(c.get("id")): c for c in all_creds if c.get("id") is not None}

    redirectable = []
    seen = set()
    for cred_id, cred_key in cred_ids:
        if cred_id in seen:
            continue
        seen.add(cred_id)
        cred = by_id.get(cred_id, {})
        cred_type = cred.get("type", "")
        if cred_type in CREDENTIAL_REDIRECT_CONFIG:
            redirectable.append({
                "id": cred_id,
                "name": cred.get("name", "?"),
                "type": cred_type,
                "provider": CREDENTIAL_REDIRECT_CONFIG[cred_type]["provider"],
            })

    return redirectable


def build_ascerta_proxy_node(
    original: dict,
    ascerta_cred: dict,
    provider_key: str,
    new_name: str,
) -> dict:
    """Build a Ascerta Proxy node from a native OpenAI app node."""
    params = original.get("parameters", {})

    # The native OpenAI node uses 'model' — newer n8n versions (2.x) store
    # this as a resourceLocator object {"mode": "list", "value": "gpt-4o"}.
    model = params.get("model", "gpt-4o")
    if isinstance(model, dict):
        model = model.get("value", "gpt-4o")

    # Try to extract messages — the native node uses structured fields or prompt
    messages = params.get("messages", params.get("prompt", ""))
    if isinstance(messages, str) and messages.startswith("["):
        pass  # already a JSON array string, keep as-is
    elif isinstance(messages, str) and messages:
        # Convert simple prompt string to messages array
        messages = json.dumps([{"role": "user", "content": messages}])
    elif isinstance(messages, list):
        messages = json.dumps(messages)
    elif isinstance(messages, dict):
        # Some nodes use {values: [{...}]} format
        values = messages.get("values", [])
        converted = []
        for v in values:
            role = v.get("role", "user")
            content = v.get("content", "")
            converted.append({"role": role, "content": content})
        messages = json.dumps(converted) if converted else '[{"role": "user", "content": "Hello!"}]'

    if not messages:
        messages = '[{"role": "user", "content": "Hello!"}]'

    new_node = {
        "id": original.get("id", ""),
        "name": new_name,
        "type": "@ascerta/n8n-nodes-ascerta.ascerta",
        "typeVersion": 1,
        "position": original.get("position", [0, 0]),
        "parameters": {
            "provider": "openai",
            "providerApiKey": provider_key,
            "model": model,
            "messages": messages,
            # Tracking defaults
            "useCaseName": "={{ $workflow.name.replaceAll(' ', '-') }}",
            "useCaseId": "={{ 'openai/' + $parameter.model + '/' + $execution.id }}",
            "useCaseStep": "={{ $node.name }}",
            # Output defaults
            "includeCostData": True,
            "returnFullResponse": False,
            "debugLogging": False,
        },
        "credentials": {
            "ascertaApi": {
                "id": str(ascerta_cred["id"]),
                "name": ascerta_cred["name"],
            },
        },
    }
    return new_node


# ── Connection Rewiring ──────────────────────────────────────────────────────

def unique_node_name(desired: str, existing_names: set) -> str:
    """Return a unique node name, appending a numeric suffix if needed."""
    if desired not in existing_names:
        return desired
    i = 1
    while f"{desired} {i}" in existing_names:
        i += 1
    return f"{desired} {i}"


def rewire_connections(connections: dict, old_name: str, new_name: str) -> dict:
    """Rename a node in the connections map (both as key and as target)."""
    if old_name == new_name:
        return connections

    new_connections = {}
    for source_name, source_conns in connections.items():
        key = new_name if source_name == old_name else source_name
        new_source_conns = {}
        for conn_type, conn_list in source_conns.items():
            new_conn_list = []
            for slot_connections in conn_list:
                new_slot = []
                for conn in slot_connections:
                    c = dict(conn)
                    if c.get("node") == old_name:
                        c["node"] = new_name
                    new_slot.append(c)
                new_conn_list.append(new_slot)
            new_source_conns[conn_type] = new_conn_list
        new_connections[key] = new_source_conns
    return new_connections


# ── Expression Reference Scanning ────────────────────────────────────────────

def fix_expression_references(nodes: list, old_name: str, new_name: str, dry_run: bool = False) -> int:
    """Find and replace $('Old Name') references in node parameters. Returns count of fixes."""
    if old_name == new_name:
        return 0

    # Match $('name') or $("name") patterns
    pattern_single = re.compile(re.escape(f"$('{old_name}')"))
    pattern_double = re.compile(re.escape(f'$("{old_name}")'))

    count = 0

    def replace_in_value(value):
        nonlocal count
        if isinstance(value, str):
            new_val = pattern_single.sub(f"$('{new_name}')", value)
            new_val = pattern_double.sub(f'$("{new_name}")', new_val)
            if new_val != value:
                count += 1
            return new_val
        elif isinstance(value, dict):
            return {k: replace_in_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [replace_in_value(item) for item in value]
        return value

    for node in nodes:
        if "parameters" in node:
            node["parameters"] = replace_in_value(node["parameters"])

    return count


# ── Workflow Update ──────────────────────────────────────────────────────────

SETTINGS_ALLOWED_KEYS = {
    "saveExecutionProgress", "saveManualExecutions",
    "saveDataErrorExecution", "saveDataSuccessExecution",
    "executionTimeout", "errorWorkflow", "timezone", "executionOrder",
}


def filter_workflow_for_update(workflow: dict) -> dict:
    """Keep only fields the PUT endpoint accepts."""
    result = {k: v for k, v in workflow.items() if k in WORKFLOW_PUT_ALLOWED_FIELDS}
    # Sanitize settings to only known-good keys
    if "settings" in result and isinstance(result["settings"], dict):
        result["settings"] = {
            k: v for k, v in result["settings"].items()
            if k in SETTINGS_ALLOWED_KEYS
        }
    return result


# ── Interactive Selection ────────────────────────────────────────────────────

REPLACEMENT_LABELS = {
    "chat_model": "Ascerta Chat Model",
    "chat_model_anthropic": "Ascerta Anthropic Chat Model",
    "chat_model_azure": "Ascerta Azure OpenAI Chat Model",
    "chat_model_bedrock": "Ascerta Bedrock Chat Model",
    "chat_model_databricks": "Ascerta Databricks Chat Model",
    "proxy": "Ascerta Proxy",
    "proxy_anthropic": "Ascerta Proxy (Anthropic)",
}


def print_discovery_summary(found: list):
    """Print a nice summary table of detected AI nodes."""
    # Aggregate by provider + category
    summary = {}
    for n in found:
        provider = n["provider"]
        label = n["label"]
        key = (provider, label)
        if key not in summary:
            summary[key] = {"count": 0, "feasible": n["feasible"], "skip_reason": n.get("skip_reason", "")}
        summary[key]["count"] += 1

    print(bold("  Detected AI Nodes"))
    print()
    print(f"  {'Provider':<16} {'Node Type':<36} {'Count':>5}  {'Status'}")
    print(f"  {'─' * 16} {'─' * 36} {'─' * 5}  {'─' * 20}")

    total = 0
    migratable = 0
    for (provider, label), info in sorted(summary.items()):
        total += info["count"]
        if info["feasible"]:
            migratable += info["count"]
            status = green("Migratable")
        else:
            status = yellow("Skip") + dim(f" ({info['skip_reason'][:30]})")
        provider_label = PROVIDER_CREDENTIAL_CONFIG.get(provider, {}).get("label", provider.title())
        print(f"  {provider_label:<16} {label:<36} {info['count']:>5}  {status}")

    print(f"  {'─' * 16} {'─' * 36} {'─' * 5}  {'─' * 20}")
    print(f"  {'Total':<16} {'':<36} {total:>5}  {green(str(migratable))} migratable, {yellow(str(total - migratable))} skipped")
    print()


def prompt_select_workflows(workflows: list) -> list:
    """Let the user pick which workflows to migrate when multiple are found."""
    print(bold("  Select Workflows"))
    print()

    # Show numbered list with AI node counts per workflow
    for i, wf in enumerate(workflows, 1):
        wf_name = wf.get("name", "Untitled")
        wf_id = wf.get("id", "?")
        node_count = len(wf.get("nodes", []))
        ai_count = sum(1 for n in wf.get("nodes", []) if n.get("type", "") in NATIVE_LLM_NODES)
        ai_tag = f" ({green(str(ai_count) + ' AI node' + ('s' if ai_count != 1 else ''))})" if ai_count else dim(" (no AI nodes)")
        print(f"  {bold(f'[{i}]')} {wf_name} {dim(f'(ID: {wf_id})')}{ai_tag}")

    print()
    print(f"  {bold('[A]')} All workflows")
    print()
    answer = input(f"  Which workflow(s)? [comma-separated numbers or A]: ").strip().lower()

    if not answer or answer == "a":
        return workflows

    try:
        indices = [int(x.strip()) for x in answer.split(",")]
        selected = [workflows[i - 1] for i in indices if 1 <= i <= len(workflows)]
        if selected:
            names = ", ".join(w.get("name", "?") for w in selected)
            print(f"  Selected: {green(names)}")
        return selected
    except (ValueError, IndexError):
        print(f"  {yellow('Invalid selection')} — using all workflows")
        return workflows


def prompt_migration_strategy(found: list, redirectable_creds: list) -> str:
    """Ask the user which migration approach to use."""
    has_migratable = any(n["feasible"] for n in found)
    has_redirectable = len(redirectable_creds) > 0

    print(bold("  Migration Strategy"))
    print()

    if has_redirectable:
        print(f"  {bold('[1]')} Credential Redirect {green('(recommended)')}")
        print(f"      Change API endpoint URLs to route ALL actions through Ascerta proxy.")
        print(f"      Fastest approach — covers every endpoint for each credential.")
        cred_names = ", ".join(f"{c['name']} ({c['type']})" for c in redirectable_creds)
        print(f"      Credentials: {dim(cred_names)}")
        print()

    if has_migratable:
        print(f"  {bold('[2]')} Node Replacement {dim('(full tracking)')}")
        print(f"      Replace Chat Model nodes with Ascerta equivalents.")
        print(f"      Adds full tracking headers (use case, user ID, limits).")
        print()

    if has_redirectable and has_migratable:
        print(f"  {bold('[3]')} Both (redirect + replace)")
        print(f"      Credential redirect for all endpoints + node replacement")
        print(f"      for full tracking on Chat Model nodes.")
        print()

    print(f"  {bold('[D]')} Dry run (preview changes without applying)")
    print(f"  {bold('[Q]')} Cancel")
    print()

    default = "1" if has_redirectable else "2"
    answer = input(f"  Strategy [{default}]: ").strip().lower()
    if not answer:
        answer = default

    return answer


def prompt_select_nodes(found: list) -> list:
    """Display a numbered list and let the user pick which nodes to migrate.

    Returns the subset of *feasible* nodes the user selected.
    """
    print(bold("  Select Nodes for Replacement"))
    print()

    migratable_indices = []

    for i, n in enumerate(found):
        num = i + 1
        wf = n["workflow_name"]
        node_name = n["node"]["name"]
        label = n["label"]

        if n["feasible"]:
            tag = green("MIGRATABLE")
            migratable_indices.append(i)
            replacement = REPLACEMENT_LABELS.get(n["replacement"], "Ascerta Node")
            detail = dim(f"-> {replacement}")
        else:
            tag = yellow("SKIP")
            detail = dim(n.get("skip_reason", "not supported"))

        print(f"  {bold(str(num)):>4}  [{tag}]  {wf} / {bold(node_name)}")
        print(f"        {label}  {detail}")
        print()

    if not migratable_indices:
        return []

    migratable_nums = [str(i + 1) for i in migratable_indices]
    hint = ",".join(migratable_nums)

    print(f"  Migratable: {', '.join(migratable_nums)}")
    print()
    answer = input(f"  Migrate which nodes? [{hint} / {bold('all')} / none]: ").strip().lower()

    if not answer or answer == "all":
        return [found[i] for i in migratable_indices]
    elif answer == "none":
        return []
    else:
        selected = []
        for part in answer.replace(" ", "").split(","):
            try:
                idx = int(part) - 1
                if 0 <= idx < len(found) and found[idx]["feasible"]:
                    selected.append(found[idx])
                elif 0 <= idx < len(found):
                    print(f"  {yellow('Note')}: #{part} ({found[idx]['label']}) is not migratable, skipping")
                else:
                    print(f"  {yellow('Note')}: #{part} is not a valid number, skipping")
            except ValueError:
                print(f"  {yellow('Note')}: '{part}' is not a number, skipping")
        return selected


# ── Display Helpers ──────────────────────────────────────────────────────────

def print_banner():
    print()
    print(bold("=" * 62))
    print(bold("  Ascerta Workflow Migration"))
    print(bold("=" * 62))
    print()


# ── Main ─────────────────────────────────────────────────────────────────────

def execute_credential_redirect(client, redirectable_creds: list, ascerta_base: str, ascerta_key: str, dry_run: bool = False) -> int:
    """Redirect credentials to Ascerta proxy URLs. Returns count of redirected.

    n8n's PATCH endpoint requires ALL credential fields (including apiKey).
    We first fetch the existing credential data via ``?includeData=true``,
    merge our redirect changes, then PATCH with the complete data.
    """
    redirected = 0
    for cred in redirectable_creds:
        config = CREDENTIAL_REDIRECT_CONFIG.get(cred["type"])
        if not config:
            continue

        base = ascerta_base.rstrip("/")
        proxy_url = f"{base}{config['proxy_path']}"

        if dry_run:
            print(f'    {cyan("DRY RUN")} "{cred["name"]}" ({cred["type"]}) -> {proxy_url}')
            redirected += 1
            continue

        # Fetch existing credential data (including secrets) so the PATCH
        # includes all required fields — n8n rejects partial updates.
        existing_data = _fetch_credential_data(client, cred["id"])
        if not existing_data:
            print(f'    {yellow("SKIP")} "{cred["name"]}" — could not read credential data from n8n')
            print(f'           (Ensure n8n API supports includeData, or update credentials manually)')
            continue

        patch = build_credential_patch(cred["type"], ascerta_base, ascerta_key,
                                       existing_data=existing_data)
        if not patch:
            continue

        try:
            client.patch(f"/api/v1/credentials/{cred['id']}", patch)
            print(f'    {green("OK")} "{cred["name"]}" ({cred["type"]}) -> {proxy_url}')
            redirected += 1
        except SystemExit:
            print(f'    {red("FAIL")} "{cred["name"]}" — could not patch credential')

    return redirected


def execute_node_replacement(client, selected: list, workflows: list, ascerta_cred: dict,
                             provider_creds: dict, dry_run: bool = False, workflow_filter: str = None,
                             verbose: bool = False, dbx_cred=None) -> tuple:
    """Replace nodes in workflows. Returns (migrated_count, skipped_count)."""
    migrated = 0
    skipped = 0

    by_wf_id = {}
    for n in selected:
        wf_id = n["workflow_id"]
        if wf_id not in by_wf_id:
            by_wf_id[wf_id] = {"workflow_name": n["workflow_name"], "nodes": []}
        by_wf_id[wf_id]["nodes"].append(n)

    for wf_id, wf_info in by_wf_id.items():
        print(f'  {bold(wf_info["workflow_name"])} {dim("(ID: " + str(wf_id) + ")")}')

        if dry_run:
            if workflow_filter:
                workflow = copy.deepcopy(workflows[0])
            else:
                workflow = copy.deepcopy(client.get(f"/api/v1/workflows/{wf_id}"))
        else:
            workflow = client.get(f"/api/v1/workflows/{wf_id}")

        # Save a pristine deep copy BEFORE any modifications for the backup
        original_workflow_snapshot = copy.deepcopy(workflow)

        nodes = workflow.get("nodes", [])
        connections = workflow.get("connections", {})
        existing_names = {n["name"] for n in nodes}
        modified = False

        for node_info in wf_info["nodes"]:
            node = node_info["node"]
            old_name = node["name"]
            provider = node_info["provider"]

            # For chat_model_* replacements, credentials are inherited from the
            # original node — no separate provider key needed.
            # For proxy_* replacements, the provider key is still needed as a parameter.
            cred_val = provider_creds.get(provider, "") if provider_creds else ""

            replacement_type = node_info["replacement"]
            replacement_label = REPLACEMENT_LABELS.get(replacement_type, "Ascerta Node")
            desired_name = replacement_label
            new_name = unique_node_name(desired_name, existing_names - {old_name})

            # Dispatch to the right builder.
            # Note: chat_model_databricks has TWO routing paths because Databricks
            # nodes can come from either (a) the community node n8n-nodes-databricks.*
            # which lands in NATIVE_LLM_NODES and uses the *_community_node builder,
            # or (b) an lmChatOpenAi shim that find_llm_nodes reclassified — those
            # entries carry a "databricks_shim" key and use the shim builder.
            builder_map = {
                "chat_model": build_ascerta_chat_model_node,
                "chat_model_anthropic": build_ascerta_chat_model_anthropic_node,
                "chat_model_azure": build_ascerta_chat_model_azure_node,
                "chat_model_bedrock": build_ascerta_chat_model_bedrock_node,
                "chat_model_databricks": build_ascerta_chat_model_databricks_node,  # placeholder; routed below
                "proxy": build_ascerta_proxy_node,
                "proxy_anthropic": build_ascerta_proxy_anthropic_node,
            }
            builder = builder_map.get(replacement_type)
            if not builder:
                print(f'    {yellow("SKIP")} "{old_name}" — no builder for {replacement_type}')
                skipped += 1
                continue

            if replacement_type == "chat_model_databricks":
                # --databricks-cloud override (set by main() when the user
                # passes a non-default value) applies to both the shim and
                # community-node paths.
                cloud_override = getattr(client, "_databricks_cloud_override", None)
                if node_info.get("databricks_shim"):
                    # Shim path: lmChatOpenAi reclassified as Databricks.
                    shim = node_info.get("databricks_shim", {})
                    cloud = shim.get("cloud_provider") or "aws"
                    if cloud == "aws" and cloud_override:
                        cloud = cloud_override
                    new_node = build_ascerta_chat_model_databricks_node(
                        node, ascerta_cred, dbx_cred, cloud, new_name,
                    )
                else:
                    # Community-node path: n8n-nodes-databricks.* in NATIVE_LLM_NODES.
                    new_node = build_ascerta_chat_model_databricks_community_node(
                        node, ascerta_cred, cred_val, new_name,
                        cloud_provider=cloud_override or "aws",
                        dbx_cred=dbx_cred,
                    )
            else:
                new_node = builder(node, ascerta_cred, cred_val, new_name)

            # Log credential passthrough details in verbose mode
            if verbose:
                orig_creds = node.get("credentials", {})
                new_creds = new_node.get("credentials", {})
                print(f'       {dim("[CREDS]")} Original node credentials: {json.dumps(orig_creds)}')
                print(f'       {dim("[CREDS]")} New node credentials:      {json.dumps(new_creds)}')

            for i, n in enumerate(nodes):
                if n.get("name") == old_name and n.get("type") == node_info["node_type"]:
                    nodes[i] = new_node
                    break

            existing_names.discard(old_name)
            existing_names.add(new_name)
            connections = rewire_connections(connections, old_name, new_name)
            ref_fixes = fix_expression_references(nodes, old_name, new_name, dry_run=dry_run)

            if dry_run:
                print(f'    {cyan("DRY RUN")} "{old_name}" -> "{new_name}"')
            else:
                print(f'    {green("OK")} "{old_name}" -> "{new_name}"')

            if ref_fixes:
                print(f'       Updated {ref_fixes} expression reference(s)')

            migrated += 1
            modified = True

        if modified and not dry_run:
            # Save a backup copy using the PRISTINE snapshot (before any modifications)
            try:
                backup_body = filter_workflow_for_update(original_workflow_snapshot)
                original_name = original_workflow_snapshot.get("name", "Untitled")
                backup_body["name"] = f"{original_name} (Pre-Migration Backup)"
                backup_resp = client.post("/api/v1/workflows", backup_body)
                backup_id = backup_resp.get("id", "?")
                print(f'    {dim(f"Backup saved as ID {backup_id}")}'  )
            except Exception as e:
                print(f'    {yellow("WARNING")}: Could not create backup: {e}')

            # Update the original workflow with migrated nodes and new name
            workflow["nodes"] = nodes
            workflow["connections"] = connections
            workflow["name"] = f"{original_workflow_snapshot.get('name', 'Untitled')} (Ascerta)"
            update_body = filter_workflow_for_update(workflow)
            put_resp = client.put(f"/api/v1/workflows/{wf_id}", update_body)
            print(f'    {green("Saved")} as "{workflow["name"]}"')

            # Verify credentials survived the PUT (n8n may strip them for
            # unrecognised node types or missing credential associations)
            saved_nodes = put_resp.get("nodes", [])
            cred_warnings = []
            for sn in saved_nodes:
                if sn.get("type", "").startswith("@ascerta/n8n-nodes-ascerta."):
                    saved_creds = sn.get("credentials", {})
                    if not saved_creds:
                        cred_warnings.append(sn.get("name", "?"))
                    elif verbose:
                        print(f'       {dim("[VERIFY]")} {sn["name"]} credentials saved: {json.dumps(saved_creds)}')
            if cred_warnings:
                print(f'    {yellow("WARNING")}: Credentials NOT saved for: {", ".join(cred_warnings)}')
                print(f'           Open each node in n8n and select the credentials manually.')
                print(f'           (This can happen if n8n hasn\'t loaded the Ascerta community node; try restarting n8n.)')

        print()

    return migrated, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Migrate n8n workflows from native LLM nodes to Ascerta nodes",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without modifying anything")
    parser.add_argument("--auto-yes", action="store_true",
                        help="Skip interactive selection — migrate all feasible nodes")
    parser.add_argument("--workflow", metavar="ID",
                        help="Migrate only the specified workflow ID")
    parser.add_argument("--verbose", action="store_true",
                        help="Show detailed API request/response logging")
    parser.add_argument("--strategy", choices=["redirect", "replace", "both"],
                        help="Migration strategy (skip interactive prompt)")
    parser.add_argument("--databricks-cloud",
                        choices=["aws", "azure", "google"],
                        default="aws",
                        help="Default cloud for ambiguous *.cloud.databricks.com hostnames in non-interactive mode")
    parser.add_argument("--databricks-credential-id", metavar="ID",
                        help="Pin a specific ascertaDatabricksApi credential ID; skips discovery")
    args = parser.parse_args()

    print_banner()

    # ── Step 1: Connection Setup ─────────────────────────────────────────
    print(bold("  Step 1: Connection Setup"))
    print()

    # Check if all env vars are present (CI/non-interactive mode)
    env_vars_present = all(os.environ.get(v) for v in ["N8N_BASE_URL", "N8N_API_KEY", "ASCERTA_BASE_URL", "ASCERTA_API_KEY"])

    if env_vars_present:
        n8n_base = os.environ["N8N_BASE_URL"].rstrip("/")
        n8n_key = os.environ["N8N_API_KEY"]
        ascerta_base = os.environ["ASCERTA_BASE_URL"].rstrip("/")
        ascerta_key = os.environ["ASCERTA_API_KEY"]
        print(f"  {green('Using environment variables')}")
    elif _is_interactive():
        details = setup_connection_details(args)
        n8n_base = details["n8n_base"]
        n8n_key = details["n8n_key"]
        ascerta_base = details["ascerta_base"]
        ascerta_key = details["ascerta_key"]
    else:
        print(f"{red('ERROR')}: Missing environment variables (non-interactive mode).")
        print("  Set: N8N_BASE_URL, N8N_API_KEY, ASCERTA_BASE_URL, ASCERTA_API_KEY")
        return 1

    print()
    print(f"  n8n instance:  {cyan(n8n_base)}")
    print(f"  Ascerta base:    {cyan(ascerta_base)}")
    if args.dry_run:
        print(f"  Mode:          {yellow('DRY RUN')} (no changes will be made)")
    print()

    client = N8nApiClient(n8n_base, n8n_key, verbose=args.verbose)

    # ── Step 2: Scan Workflows ───────────────────────────────────────────
    print(bold("  Step 2: Scanning workflows"))
    print()

    if args.workflow:
        wf_data = client.get(f"/api/v1/workflows/{args.workflow}")
        workflows = [wf_data]
    else:
        wf_resp = client.get("/api/v1/workflows")
        workflows = wf_resp.get("data", wf_resp) if isinstance(wf_resp, dict) else wf_resp
        if isinstance(workflows, dict):
            workflows = [workflows]

    if not workflows:
        print("  No workflows found.")
        return 0

    # For list endpoints that return partial data, fetch full workflows
    full_workflows = []
    for wf in workflows:
        if isinstance(wf.get("nodes"), list) and isinstance(wf.get("connections"), dict):
            full_workflows.append(wf)
        else:
            wf_id = wf.get("id")
            if wf_id:
                full_workflows.append(client.get(f"/api/v1/workflows/{wf_id}"))
    workflows = full_workflows

    # ── Workflow selection (interactive) ─────────────────────────────
    if not args.workflow and len(workflows) > 1 and _is_interactive() and not args.auto_yes:
        workflows = prompt_select_workflows(workflows)
        if not workflows:
            print("  No workflows selected. Exiting.")
            return 0
        print()

    found = find_llm_nodes(workflows, client=client)
    # Collect credential IDs used by Databricks-shim nodes — these point at a
    # Databricks workspace, not OpenAI, so they must NOT be redirected through
    # Ascerta's OpenAI proxy path. Filter them out of the redirect set.
    # Normalize IDs to str — n8n versions vary between int and str.
    shim_cred_ids = {
        str(c["id"])
        for n in found
        if n.get("databricks_shim", {}).get("detected")
        for c in (n["node"].get("credentials") or {}).values()
        if isinstance(c, dict) and c.get("id")
    }
    redirectable_creds = [
        c for c in find_redirectable_credentials(client, workflows)
        if str(c["id"]) not in shim_cred_ids
    ]
    databricks_nodes = find_databricks_nodes(workflows)

    if not found and not redirectable_creds and not databricks_nodes:
        print("  No AI nodes or redirectable credentials found. Nothing to migrate.")
        return 0

    print(f"  Scanned {len(workflows)} workflow(s), found {len(found)} AI node(s)")
    if redirectable_creds:
        print(f"  Found {len(redirectable_creds)} redirectable credential(s)")
    if databricks_nodes:
        print(f"  Found {yellow(str(len(databricks_nodes)))} Databricks/AgentBricks node(s)")
    print()

    # ── Databricks/AgentBricks Warnings ──────────────────────────────────
    # Known Databricks types in NATIVE_LLM_NODES are auto-migrated above.
    # This section warns about additional Databricks nodes (unknown community
    # node types, HTTP Request nodes calling Databricks URLs) that can't be
    # auto-migrated but should be reviewed.
    if databricks_nodes:
        print(yellow(bold("  ⚠ Additional Databricks / AgentBricks Detected")))
        print()
        for dbx in databricks_nodes:
            print(f"    • {bold(dbx['node_name'])} ({dim(dbx['node_type'])})")
            print(f"      Workflow: {dbx['workflow_name']} (ID: {dbx['workflow_id']})")
            print(f"      Reason:   {dbx['reason']}")
        print()
        print(f"  {yellow('Note:')} These {len(databricks_nodes)} node(s) use non-standard Databricks")
        print(f"  types and require manual replacement with Ascerta Databricks (Proxy).")
        print()

    if found:
        print_discovery_summary(found)

    # ── Step 3: Choose Strategy ──────────────────────────────────────────
    print(bold("  Step 3: Choose migration strategy"))
    print()

    if args.strategy:
        strategy = {"redirect": "1", "replace": "2", "both": "3"}[args.strategy]
    elif args.auto_yes:
        strategy = "3" if redirectable_creds else "2"
        print(f"  Auto-selected: {'both' if strategy == '3' else 'node replacement'}")
        print()
    else:
        strategy = prompt_migration_strategy(found, redirectable_creds)

    dry_run = args.dry_run or strategy.lower() == "d"
    if strategy.lower() == "q":
        print("  Cancelled.")
        return 0

    do_redirect = strategy in ("1", "3")
    do_replace = strategy in ("2", "3")

    # ── Step 4: Collect Credentials ──────────────────────────────────────
    print(bold("  Step 4: Credentials"))
    print()

    ascerta_cred = {"id": "dry-run", "name": "Ascerta API (dry run)"}
    provider_creds = {}

    if not dry_run and do_replace:
        ascerta_cred = ensure_ascerta_credential(client, ascerta_key, ascerta_base)
        print()

    if do_replace:
        selected = [n for n in found if n["feasible"]]
        if not args.auto_yes and _is_interactive():
            selected = prompt_select_nodes(found)
            print()

        if not dry_run and selected:
            # Chat model nodes use credential passthrough (the existing provider
            # credential is copied to the Ascerta node) — no API key needed.
            # Proxy nodes still need provider API keys as node parameters.
            proxy_nodes = [n for n in selected if n.get("replacement", "").startswith("proxy")]
            if proxy_nodes:
                provider_creds = collect_provider_credentials(proxy_nodes)
                print()
            else:
                print(f"  {green('Provider credentials inherited')} from existing nodes (no re-entry needed)")
                print()
    else:
        selected = []

    dbx_cred = None
    if do_replace and any(n.get("replacement") == "chat_model_databricks" for n in selected):
        dbx_cred = resolve_ascerta_databricks_credential(client, args, dry_run=dry_run)
        # Stash the cloud override on the client for builder dispatch.
        setattr(client, "_databricks_cloud_override",
                args.databricks_cloud if args.databricks_cloud != "aws" else None)
        print()

    # ── Step 5: Execute Migration ────────────────────────────────────────
    print(bold("  Step 5: Migrating"))
    print()

    creds_redirected = 0
    nodes_migrated = 0
    nodes_skipped = 0

    # Credential redirect
    if do_redirect and redirectable_creds:
        print(bold("  Credential Redirects:"))
        print()
        creds_redirected = execute_credential_redirect(client, redirectable_creds, ascerta_base, ascerta_key, dry_run=dry_run)
        print()

    # Node replacement
    if do_replace and selected:
        print(bold("  Node Replacements:"))
        print()
        nodes_migrated, nodes_skipped = execute_node_replacement(
            client, selected, workflows, ascerta_cred, provider_creds,
            dry_run=dry_run, workflow_filter=args.workflow, verbose=args.verbose,
            dbx_cred=dbx_cred,
        )

    infeasible_count = len([n for n in found if not n["feasible"]])
    total_skipped = nodes_skipped + infeasible_count

    # ── Summary ──────────────────────────────────────────────────────────
    print(bold("=" * 62))
    tag = yellow("DRY RUN") if dry_run else green("COMPLETE")
    print(f"  Migration {tag}")
    print()
    if creds_redirected:
        print(f"  Credentials redirected: {green(str(creds_redirected)) if not dry_run else cyan(str(creds_redirected))}")
    if nodes_migrated:
        print(f"  Nodes replaced:        {green(str(nodes_migrated)) if not dry_run else cyan(str(nodes_migrated))}")
    if total_skipped:
        print(f"  Nodes skipped:         {yellow(str(total_skipped))}")
    if not creds_redirected and not nodes_migrated:
        print(f"  {yellow('No changes made.')}")
    print(bold("=" * 62))
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
