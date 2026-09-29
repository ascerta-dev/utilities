#!/usr/bin/env python3
"""
audit-configure-ascerta-proxy.py

Audit n8n workflows for LLM usage and optionally configure credentials
to route through Ascerta proxy URLs.

This script is designed to answer:
  - What LLM providers/nodes are used?
  - Where are they used (connections + expression refs)?
  - Which credentials should be switched to Ascerta proxy?
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional


# Native and Ascerta node coverage used by this audit tool.
NATIVE_NODE_TYPES = {
    # ── OpenAI ──────────────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatOpenAi": {
        "provider": "openai",
        "category": "langchain_chat_model",
        "label": "OpenAI Chat Model (LangChain)",
        "redirectable": True,
        "recommended_action": "credential_redirect_or_replace_with_ascerta_node",
    },
    "@n8n/n8n-nodes-langchain.openai": {
        "provider": "openai",
        "category": "app_node",
        "label": "OpenAI (App Node — 16 actions)",
        "redirectable": True,
        "recommended_action": "credential_redirect_or_replace_with_ascerta_proxy",
    },
    "@n8n/n8n-nodes-langchain.lmOpenAi": {
        "provider": "openai",
        "category": "langchain_completion_model",
        "label": "OpenAI Completion Model",
        "redirectable": True,
        "recommended_action": "credential_redirect_or_replace_with_ascerta_node",
    },
    "@n8n/n8n-nodes-langchain.embeddingsOpenAi": {
        "provider": "openai",
        "category": "embeddings",
        "label": "OpenAI Embeddings",
        "redirectable": True,
        "recommended_action": "credential_redirect",
    },
    # ── Anthropic ───────────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatAnthropic": {
        "provider": "anthropic",
        "category": "langchain_chat_model",
        "label": "Anthropic Chat Model (LangChain)",
        "redirectable": True,
        "recommended_action": "credential_redirect_or_replace_with_ascerta_node",
    },
    "@n8n/n8n-nodes-langchain.anthropic": {
        "provider": "anthropic",
        "category": "app_node",
        "label": "Anthropic (App Node — 10 actions)",
        "redirectable": True,
        "recommended_action": "credential_redirect_or_replace_with_ascerta_proxy",
    },
    # ── Azure OpenAI ────────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatAzureOpenAi": {
        "provider": "azureOpenai",
        "category": "langchain_chat_model",
        "label": "Azure OpenAI Chat Model (LangChain)",
        "redirectable": True,
        "recommended_action": "credential_redirect_or_replace_with_ascerta_node",
    },
    "@n8n/n8n-nodes-langchain.embeddingsAzureOpenAi": {
        "provider": "azureOpenai",
        "category": "embeddings",
        "label": "Azure OpenAI Embeddings",
        "redirectable": True,
        "recommended_action": "credential_redirect",
    },
    # ── AWS Bedrock ─────────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatAwsBedrock": {
        "provider": "bedrock",
        "category": "langchain_chat_model",
        "label": "AWS Bedrock Chat Model (LangChain)",
        "redirectable": False,
        "recommended_action": "replace_with_ascerta_node",
    },
    "@n8n/n8n-nodes-langchain.embeddingsAwsBedrock": {
        "provider": "bedrock",
        "category": "embeddings",
        "label": "AWS Bedrock Embeddings",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    # ── Google ──────────────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatGoogleGemini": {
        "provider": "google",
        "category": "langchain_chat_model",
        "label": "Google Gemini Chat Model",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.lmChatGoogleVertex": {
        "provider": "google",
        "category": "langchain_chat_model",
        "label": "Google Vertex Chat Model",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.googleGemini": {
        "provider": "google",
        "category": "app_node",
        "label": "Google Gemini (App Node)",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.embeddingsGoogleGemini": {
        "provider": "google",
        "category": "embeddings",
        "label": "Google Gemini Embeddings",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.embeddingsGoogleVertex": {
        "provider": "google",
        "category": "embeddings",
        "label": "Google Vertex Embeddings",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    # ── Other providers ─────────────────────────────────────────────────────
    "@n8n/n8n-nodes-langchain.lmChatMistralCloud": {
        "provider": "mistral",
        "category": "langchain_chat_model",
        "label": "Mistral Chat Model",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.embeddingsMistralCloud": {
        "provider": "mistral",
        "category": "embeddings",
        "label": "Mistral Embeddings",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.lmChatGroq": {
        "provider": "groq",
        "category": "langchain_chat_model",
        "label": "Groq Chat Model",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.lmChatDeepSeek": {
        "provider": "deepseek",
        "category": "langchain_chat_model",
        "label": "DeepSeek Chat Model",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.lmChatCohere": {
        "provider": "cohere",
        "category": "langchain_chat_model",
        "label": "Cohere Chat Model",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.embeddingsCohere": {
        "provider": "cohere",
        "category": "embeddings",
        "label": "Cohere Embeddings",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.lmChatXAiGrok": {
        "provider": "xai",
        "category": "langchain_chat_model",
        "label": "xAI Grok Chat Model",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.lmChatOpenRouter": {
        "provider": "openrouter",
        "category": "langchain_chat_model",
        "label": "OpenRouter Chat Model",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.lmChatOllama": {
        "provider": "ollama",
        "category": "langchain_chat_model",
        "label": "Ollama Chat Model",
        "redirectable": False,
        "recommended_action": "not_applicable_local",
    },
    "@n8n/n8n-nodes-langchain.lmOllama": {
        "provider": "ollama",
        "category": "langchain_completion_model",
        "label": "Ollama Completion Model",
        "redirectable": False,
        "recommended_action": "not_applicable_local",
    },
    "@n8n/n8n-nodes-langchain.embeddingsOllama": {
        "provider": "ollama",
        "category": "embeddings",
        "label": "Ollama Embeddings",
        "redirectable": False,
        "recommended_action": "not_applicable_local",
    },
    "@n8n/n8n-nodes-langchain.lmChatVercelAiGateway": {
        "provider": "vercel",
        "category": "langchain_chat_model",
        "label": "Vercel AI Gateway Chat Model",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.lmOpenHuggingFaceInference": {
        "provider": "huggingface",
        "category": "langchain_completion_model",
        "label": "HuggingFace Inference Model",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    "@n8n/n8n-nodes-langchain.embeddingsHuggingFaceInference": {
        "provider": "huggingface",
        "category": "embeddings",
        "label": "HuggingFace Embeddings",
        "redirectable": False,
        "recommended_action": "manual_work_required",
    },
    # ── Databricks / AgentBricks ─────────────────────────────────────────────
    "n8n-nodes-databricks.databricks": {
        "provider": "databricks",
        "category": "community_node",
        "label": "Databricks (Community Node)",
        "redirectable": False,
        "recommended_action": "replace_with_ascerta_node",
    },
    "n8n-nodes-databricks.lmChatDatabricks": {
        "provider": "databricks",
        "category": "community_node",
        "label": "Databricks Chat Model (Community Node)",
        "redirectable": False,
        "recommended_action": "replace_with_ascerta_node",
    },
    "n8n-nodes-databricks.databricksAiAgent": {
        "provider": "databricks",
        "category": "community_node",
        "label": "Databricks AI Agent (Community Node)",
        "redirectable": False,
        "recommended_action": "replace_with_ascerta_node",
    },
}

ASCERTA_NODE_TYPES = {
    "@ascerta/n8n-nodes-ascerta.ascerta": {
        "provider": "ascerta_proxy",
        "category": "ascerta_proxy",
        "label": "Ascerta Proxy",
    },
    "@ascerta/n8n-nodes-ascerta.lmChatAscerta": {
        "provider": "ascerta_chat_model",
        "category": "ascerta_chat_model",
        "label": "Ascerta OpenAI (Proxy)",
    },
    "@ascerta/n8n-nodes-ascerta.lmChatAscertaAnthropic": {
        "provider": "ascerta_chat_model_anthropic",
        "category": "ascerta_chat_model",
        "label": "Ascerta Anthropic (Proxy)",
    },
    "@ascerta/n8n-nodes-ascerta.lmChatAscertaAzure": {
        "provider": "ascerta_chat_model_azure",
        "category": "ascerta_chat_model",
        "label": "Ascerta Azure AI Foundry (Proxy)",
    },
    "@ascerta/n8n-nodes-ascerta.lmChatAscertaBedrock": {
        "provider": "ascerta_chat_model_bedrock",
        "category": "ascerta_chat_model",
        "label": "Ascerta Amazon Bedrock (Proxy)",
    },
    "@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks": {
        "provider": "ascerta_chat_model_databricks",
        "category": "ascerta_chat_model",
        "label": "Ascerta Databricks (Proxy)",
    },
}

# n8n credential types known to the toolkit. Values used only for display /
# classification — `ascertaApi` and `ascertaDatabricksApi` are not redirect-eligible
# (they already point at Ascerta), but listing them keeps audit reports from
# tagging them as unknown.
KNOWN_ASCERTA_CREDENTIAL_TYPES = {
    "ascertaApi": "ascerta",
    "ascertaDatabricksApi": "ascerta_databricks",
}

SUPPORTED_CREDENTIAL_REDIRECT_TYPES = {
    "openAiApi": "openai",
    "anthropicApi": "anthropic",
    "azureOpenAiApi": "azureOpenai",
}

PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azureOpenai": "AZURE_OPENAI_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
}


# ── Databricks Shim Detection (duplicate of migrator helper, see spec §11) ─
# NOTE: This intentionally duplicates `classify_databricks_shim` from
# migrate-workflows-to-ascerta.py. The plan (§11) chose duplication over a shared
# module to keep both scripts self-contained and runnable standalone. Keep the
# two copies in sync when changing detection logic.

DATABRICKS_HOSTNAME_SUFFIXES = {
    ".azuredatabricks.net": "azure",
    ".cloud.databricks.com": "aws",
}


def _classify_databricks_hostname(url: Optional[str]) -> Optional[str]:
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
    """Return {detected, cloud_provider, source} for an lmChatOpenAi node.

    `client` is unused in the audit version — kept for signature parity
    with the migrator's helper. The audit version is intentionally
    pure: no credential probes, no I/O.
    """
    params = node.get("parameters", {}) or {}
    options = params.get("options", {}) or {}
    base_url = options.get("baseURL") if isinstance(options, dict) else None
    cloud = _classify_databricks_hostname(base_url) if base_url else None
    if cloud:
        return {"detected": True, "cloud_provider": cloud, "source": "node_param"}
    # No credential probe in audit by default — keeps build_analysis_report pure
    return {"detected": False, "cloud_provider": None, "source": "none"}


class N8nApiClient:
    def __init__(self, base_url: str, api_key: str, verbose: bool = False, insecure: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.verbose = verbose
        self.context = ssl._create_unverified_context() if insecure else None

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        fail_on_error: bool = True,
    ) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-N8N-API-KEY", self.api_key)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, context=self.context) as resp:
                payload = resp.read().decode("utf-8")
                if self.verbose:
                    print(f"[API] {method} {path} -> {resp.status}")
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as err:
            body_text = err.read().decode("utf-8", errors="replace")
            if not fail_on_error:
                return {
                    "_error": {
                        "status": err.code,
                        "body": body_text[:700],
                    }
                }
            print(f"ERROR: {method} {path} -> HTTP {err.code}")
            print(body_text[:700])
            raise SystemExit(1)

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def get_optional(self, path: str) -> dict:
        return self._request("GET", path, fail_on_error=False)

    def patch(self, path: str, body: dict) -> dict:
        return self._request("PATCH", path, body)


def _extract_data(response: object) -> list:
    if isinstance(response, dict):
        if isinstance(response.get("data"), list):
            return response["data"]
        if "id" in response:
            return [response]
        return []
    if isinstance(response, list):
        return response
    return []


def fetch_workflows(client: N8nApiClient, workflow_id: Optional[str] = None) -> list:
    if workflow_id:
        return [client.get(f"/api/v1/workflows/{workflow_id}")]

    listed = _extract_data(client.get("/api/v1/workflows"))
    workflows = []
    seen_ids = set()
    for wf in listed:
        wf_id = str(wf.get("id", "")).strip()
        if not wf_id or wf_id in seen_ids:
            continue
        seen_ids.add(wf_id)
        if isinstance(wf.get("nodes"), list) and isinstance(wf.get("connections"), dict):
            workflows.append(wf)
        else:
            workflows.append(client.get(f"/api/v1/workflows/{wf_id}"))
    return workflows


def find_expression_references(nodes: list, target_name: str) -> List[dict]:
    pattern_single = re.compile(re.escape(f"$('{target_name}')"))
    pattern_double = re.compile(re.escape(f'$("{target_name}")'))
    refs = []

    def count_hits(value: object) -> int:
        if isinstance(value, str):
            return len(pattern_single.findall(value)) + len(pattern_double.findall(value))
        if isinstance(value, dict):
            return sum(count_hits(v) for v in value.values())
        if isinstance(value, list):
            return sum(count_hits(v) for v in value)
        return 0

    for node in nodes:
        params = node.get("parameters", {})
        hits = count_hits(params)
        if hits:
            refs.append({"node": node.get("name", "?"), "count": hits})
    return refs


def incoming_edges(connections: dict, node_name: str) -> List[dict]:
    incoming = []
    for source_name, source_map in connections.items():
        if not isinstance(source_map, dict):
            continue
        for conn_type, slots in source_map.items():
            if not isinstance(slots, list):
                continue
            for slot_index, slot in enumerate(slots):
                if not isinstance(slot, list):
                    continue
                for conn in slot:
                    if isinstance(conn, dict) and conn.get("node") == node_name:
                        incoming.append({
                            "source": source_name,
                            "type": conn_type,
                            "slot": slot_index,
                        })
    return incoming


def outgoing_edges(connections: dict, node_name: str) -> List[dict]:
    outgoing = []
    source_map = connections.get(node_name, {})
    if not isinstance(source_map, dict):
        return outgoing
    for conn_type, slots in source_map.items():
        if not isinstance(slots, list):
            continue
        for slot_index, slot in enumerate(slots):
            if not isinstance(slot, list):
                continue
            for conn in slot:
                if isinstance(conn, dict):
                    outgoing.append({
                        "target": conn.get("node", "?"),
                        "type": conn_type,
                        "slot": slot_index,
                    })
    return outgoing


def extract_action_signature(node: dict) -> dict:
    params = node.get("parameters", {})
    signature = {}
    candidate_keys = (
        "resource",
        "operation",
        "action",
        "mode",
        "model",
        "endpoint",
        "apiVersion",
        "azureDeploymentName",
        "promptType",
        "requestType",
    )
    for key in candidate_keys:
        if key in params:
            signature[key] = params.get(key)

    # Preserve whether this node bypasses structured fields with raw payload.
    if "rawBody" in params:
        signature["usesRawBody"] = bool(params.get("rawBody"))
    return signature


def extract_credential_refs(node: dict) -> List[dict]:
    refs = []
    for cred_key, cred_info in (node.get("credentials", {}) or {}).items():
        if not isinstance(cred_info, dict):
            continue
        cred_id = str(cred_info.get("id", "")).strip()
        if not cred_id:
            continue
        refs.append({
            "credential_key": cred_key,
            "credential_id": cred_id,
            "credential_name": cred_info.get("name", "?"),
        })
    return refs


def build_analysis_report(workflows: list) -> dict:
    nodes_report = []
    credentials_usage: Dict[str, dict] = {}
    provider_counts: Dict[str, int] = {}

    for wf in workflows:
        wf_id = str(wf.get("id", "?"))
        wf_name = wf.get("name", "Untitled")
        nodes = wf.get("nodes", [])
        connections = wf.get("connections", {})

        for node in nodes:
            node_type = node.get("type", "")
            source = None
            if node_type in NATIVE_NODE_TYPES:
                source = "native"
                info = NATIVE_NODE_TYPES[node_type]
            elif node_type in ASCERTA_NODE_TYPES:
                source = "ascerta"
                info = ASCERTA_NODE_TYPES[node_type]
            else:
                continue

            node_name = node.get("name", "?")
            refs = find_expression_references(nodes, node_name)
            incoming = incoming_edges(connections, node_name)
            outgoing = outgoing_edges(connections, node_name)

            provider = info["provider"]
            provider_counts[provider] = provider_counts.get(provider, 0) + 1

            node_entry = {
                "workflow_id": wf_id,
                "workflow_name": wf_name,
                "node_name": node_name,
                "node_type": node_type,
                "label": info["label"],
                "source": source,
                "provider": provider,
                "category": info["category"],
                "incoming": incoming,
                "outgoing": outgoing,
                "expression_references": refs,
                "action_signature": extract_action_signature(node),
                "recommended_action": info.get("recommended_action", "already_on_ascerta"),
                "redirectable": info.get("redirectable", False),
                "credentials": node.get("credentials", {}),
                "credential_refs": extract_credential_refs(node),
            }

            # Databricks shim classification for lmChatOpenAi nodes only
            if node_type == "@n8n/n8n-nodes-langchain.lmChatOpenAi":
                shim = classify_databricks_shim(node, client=None)
                node_entry["databricks_shim"] = shim
                if shim["detected"]:
                    # Override the OpenAI recommendation entirely. A shim's
                    # credential URL points at a Databricks workspace, so the
                    # default credential_redirect path would route through
                    # Ascerta's OpenAI proxy and produce wrong cost attribution.
                    # The Databricks-specific replacement is the only correct
                    # action for these nodes.
                    node_entry["recommended_action"] = "replace_with_ascerta_databricks"

            nodes_report.append(node_entry)

            for cred_ref in node_entry["credential_refs"]:
                cred_key = cred_ref["credential_key"]
                cred_id = cred_ref["credential_id"]
                entry = credentials_usage.setdefault(cred_id, {
                    "credential_name": cred_ref["credential_name"],
                    "credential_keys": set(),
                    "used_by": [],
                })
                entry["credential_keys"].add(cred_key)
                entry["used_by"].append({
                    "workflow_id": wf_id,
                    "workflow_name": wf_name,
                    "node_name": node_name,
                    "node_type": node_type,
                    "provider": provider,
                })

    for cred in credentials_usage.values():
        cred["credential_keys"] = sorted(cred["credential_keys"])

    return {
        "summary": {
            "workflows_scanned": len(workflows),
            "tracked_nodes_found": len(nodes_report),
            "provider_counts": provider_counts,
        },
        "nodes": nodes_report,
        "credentials_usage": credentials_usage,
    }


def probe_credential_capabilities(client: N8nApiClient, cred_id: str) -> dict:
    # Try with includeData first, then fallback.
    resp = client.get_optional(f"/api/v1/credentials/{cred_id}?includeData=true")
    if resp.get("_error"):
        resp = client.get_optional(f"/api/v1/credentials/{cred_id}")
    if resp.get("_error"):
        err = resp["_error"]
        status = err.get("status")
        probe_status = "api_does_not_expose_credential_data" if status == 405 else "error"
        return {
            "probe_status": probe_status,
            "error": err,
            "fields_present": {},
        }

    data = resp.get("data", {})
    if not isinstance(data, dict):
        data = {}
    fields_present = {
        "apiKey": "apiKey" in data,
        "url": "url" in data,
        "endpoint": "endpoint" in data,
        "headerName": "headerName" in data,
        "headerValue": "headerValue" in data,
    }
    return {
        "probe_status": "ok",
        "fields_present": fields_present,
    }


def evaluate_redirect_capability(cred_type: str, capability: dict) -> str:
    if not cred_type or cred_type not in SUPPORTED_CREDENTIAL_REDIRECT_TYPES:
        return "not_applicable"

    status = capability.get("probe_status")
    fields = capability.get("fields_present", {})
    if status != "ok":
        return "unverified"

    if cred_type == "openAiApi":
        required = ("apiKey", "url")
    elif cred_type == "anthropicApi":
        required = ("apiKey", "url", "headerName", "headerValue")
    elif cred_type == "azureOpenAiApi":
        required = ("apiKey", "endpoint")
    else:
        return "not_applicable"

    return "likely_supported" if all(fields.get(k, False) for k in required) else "likely_unsupported"


def enrich_credentials_usage(client: N8nApiClient, report: dict) -> None:
    creds = _extract_data(client.get("/api/v1/credentials"))
    by_id = {str(c.get("id")): c for c in creds if c.get("id") is not None}
    for cred_id, usage in report["credentials_usage"].items():
        cred = by_id.get(cred_id, {})
        cred_type = cred.get("type")
        usage["credential_type"] = cred_type
        usage["n8n_credential_name"] = cred.get("name", usage.get("credential_name"))
        usage["redirect_supported"] = cred_type in SUPPORTED_CREDENTIAL_REDIRECT_TYPES
        usage["already_ascerta_credential"] = cred_type in KNOWN_ASCERTA_CREDENTIAL_TYPES
        if usage["redirect_supported"]:
            capability = probe_credential_capabilities(client, cred_id)
            usage["capability_probe"] = capability
            usage["redirect_capability"] = evaluate_redirect_capability(cred_type, capability)
        else:
            usage["capability_probe"] = {
                "probe_status": "skipped_not_redirect_type",
                "fields_present": {},
            }
            usage["redirect_capability"] = "not_applicable"


def choose_migration_action(node: dict, report: dict) -> dict:
    if node.get("source") == "ascerta":
        return {
            "path": "already_on_ascerta",
            "confidence": 1.0,
            "reason": "Node already uses Ascerta.",
        }

    # Shim path takes priority: an lmChatOpenAi pointed at a Databricks
    # workspace must NOT be redirected via the OpenAI proxy.
    if node.get("databricks_shim", {}).get("detected"):
        cloud = node["databricks_shim"].get("cloud_provider", "aws")
        return {
            "path": "replace_with_ascerta_databricks",
            "confidence": 0.97,
            "reason": (
                f"OpenAI node points at a Databricks workspace "
                f"(cloud_provider={cloud}); replace with Ascerta Databricks node."
            ),
        }

    provider = node.get("provider")
    if provider in {"google", "mistral"}:
        return {
            "path": "manual_required",
            "confidence": 0.98,
            "reason": "Provider not currently supported by Ascerta toolkit migration flows.",
        }

    if provider == "bedrock" and node.get("category") == "langchain_chat_model":
        return {
            "path": "replace_with_ascerta_proxy",
            "confidence": 0.65,
            "reason": "Bedrock native chat model is not credential-redirectable in most n8n setups.",
        }

    # Check credential capabilities for redirect-eligible providers.
    cred_ids = [c["credential_id"] for c in node.get("credential_refs", [])]
    redirect_caps = []
    for cred_id in cred_ids:
        usage = report["credentials_usage"].get(cred_id, {})
        cap = usage.get("redirect_capability")
        if cap:
            redirect_caps.append(cap)

    if redirect_caps and all(c == "likely_supported" for c in redirect_caps):
        return {
            "path": "credential_redirect",
            "confidence": 0.95,
            "reason": "Credential fields required for proxy rerouting appear present.",
        }

    if redirect_caps and any(c == "unverified" for c in redirect_caps):
        return {
            "path": "verify_then_redirect",
            "confidence": 0.55,
            "reason": "Credential schema could not be fully verified via API.",
        }

    if redirect_caps and any(c == "likely_unsupported" for c in redirect_caps):
        return {
            "path": "replace_with_ascerta_proxy",
            "confidence": 0.7,
            "reason": "Credential redirect fields appear unavailable; node replacement preferred.",
        }

    return {
        "path": "manual_required",
        "confidence": 0.4,
        "reason": "No deterministic automated path identified from current metadata.",
    }


def build_migration_manifest(report: dict) -> List[dict]:
    manifest = []
    for node in report["nodes"]:
        decision = choose_migration_action(node, report)
        manifest.append({
            "workflow_id": node["workflow_id"],
            "workflow_name": node["workflow_name"],
            "node_name": node["node_name"],
            "node_type": node["node_type"],
            "provider": node["provider"],
            "source": node["source"],
            "action_signature": node.get("action_signature", {}),
            "credential_refs": node.get("credential_refs", []),
            "blast_radius": {
                "incoming_edges": len(node.get("incoming", [])),
                "outgoing_edges": len(node.get("outgoing", [])),
                "expression_reference_count": sum(r.get("count", 0) for r in node.get("expression_references", [])),
            },
            "recommended_path": decision["path"],
            "confidence": decision["confidence"],
            "reason": decision["reason"],
        })
    return manifest


def build_patch_data(provider: str, provider_api_key: str, ascerta_base_url: str, ascerta_api_key: str) -> dict:
    base = ascerta_base_url.rstrip("/")
    if provider == "openai":
        return {
            "data": {
                "apiKey": provider_api_key,
                "url": f"{base}/api/v1/proxy/openai/v1",
                "headerName": "",
                "headerValue": "",
            }
        }
    if provider == "anthropic":
        return {
            "data": {
                "apiKey": provider_api_key,
                "url": f"{base}/api/v1/proxy/anthropic",
                "headerName": "xProxy-api-key",
                "headerValue": ascerta_api_key,
            }
        }
    if provider == "azureOpenai":
        return {
            "data": {
                "apiKey": provider_api_key,
                "endpoint": f"{base}/api/v1/proxy/azure.openai",
                "headerName": "",
                "headerValue": "",
            }
        }
    raise ValueError(f"Unsupported provider for credential redirect: {provider}")


def pick_credentials_for_redirect(report: dict) -> List[dict]:
    # Credentials used by Databricks-shim nodes point at a Databricks workspace,
    # not OpenAI. They must not be redirected through Ascerta's OpenAI proxy.
    shim_cred_ids = {
        ref["credential_id"]
        for node in report.get("nodes", [])
        if node.get("databricks_shim", {}).get("detected")
        for ref in node.get("credential_refs", [])
    }
    selected = []
    for cred_id, usage in report["credentials_usage"].items():
        if cred_id in shim_cred_ids:
            continue
        cred_type = usage.get("credential_type")
        provider = SUPPORTED_CREDENTIAL_REDIRECT_TYPES.get(cred_type)
        if not provider:
            continue
        if usage.get("redirect_capability") != "likely_supported":
            continue
        selected.append({
            "id": cred_id,
            "provider": provider,
            "credential_type": cred_type,
            "credential_name": usage.get("n8n_credential_name", usage.get("credential_name", "?")),
            "used_by": usage.get("used_by", []),
        })
    return selected


def _md_escape(value: object) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_markdown_report(report: dict) -> str:
    summary = report.get("summary", {})
    providers = summary.get("provider_counts", {})
    credentials_usage = report.get("credentials_usage", {})
    manifest = report.get("migration_manifest", [])
    nodes = report.get("nodes", [])

    lines = []
    lines.append("# Ascerta Proxy Audit Report")
    lines.append("")
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines.append(f"_Generated: {generated_at}_")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Workflows scanned: **{summary.get('workflows_scanned', 0)}**")
    lines.append(f"- Tracked nodes found: **{summary.get('tracked_nodes_found', 0)}**")
    lines.append("")

    if providers:
        lines.append("### Provider Counts")
        lines.append("")
        lines.append("| Provider | Count |")
        lines.append("|---|---:|")
        for provider, count in sorted(providers.items()):
            lines.append(f"| `{_md_escape(provider)}` | {count} |")
        lines.append("")

    if manifest:
        path_counts: Dict[str, int] = {}
        for entry in manifest:
            path = entry.get("recommended_path", "unknown")
            path_counts[path] = path_counts.get(path, 0) + 1
        lines.append("### Migration Manifest (Path Counts)")
        lines.append("")
        lines.append("| Recommended Path | Count |")
        lines.append("|---|---:|")
        for path, count in sorted(path_counts.items()):
            lines.append(f"| `{_md_escape(path)}` | {count} |")
        lines.append("")

    lines.append("## Credentials")
    lines.append("")
    if credentials_usage:
        lines.append("| Credential ID | Name | Type | Redirect Capability | Used By Nodes |")
        lines.append("|---|---|---|---|---:|")
        for cred_id, usage in sorted(credentials_usage.items()):
            lines.append(
                f"| `{_md_escape(cred_id)}` | {_md_escape(usage.get('n8n_credential_name', usage.get('credential_name', '?')))} "
                f"| `{_md_escape(usage.get('credential_type', 'unknown'))}` "
                f"| `{_md_escape(usage.get('redirect_capability', 'not_applicable'))}` "
                f"| {len(usage.get('used_by', []))} |"
            )
    else:
        lines.append("_No credentials attached to matched nodes._")
    lines.append("")

    lines.append("## Node Inventory")
    lines.append("")
    if nodes:
        lines.append("| Workflow | Node | Provider | Source | Incoming | Outgoing | Recommended Path | Confidence |")
        lines.append("|---|---|---|---|---:|---:|---|---:|")
        decision_map = {
            (m.get("workflow_id"), m.get("node_name")): m for m in manifest
        }
        for n in nodes:
            decision = decision_map.get((n.get("workflow_id"), n.get("node_name")), {})
            lines.append(
                f"| {_md_escape(n.get('workflow_name', '?'))} | {_md_escape(n.get('node_name', '?'))} "
                f"| `{_md_escape(n.get('provider', '?'))}` | `{_md_escape(n.get('source', '?'))}` "
                f"| {len(n.get('incoming', []))} | {len(n.get('outgoing', []))} "
                f"| `{_md_escape(decision.get('recommended_path', 'n/a'))}` | {decision.get('confidence', 'n/a')} |"
            )
    else:
        lines.append("_No known native/Ascerta nodes found._")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- `unverified` redirect capability means credential data fields could not be fully inspected via API on this n8n instance.")
    lines.append("- `already_on_ascerta` nodes are already routed through Ascerta and require no migration action.")
    lines.append("")
    return "\n".join(lines)


def collect_provider_key(provider: str, credential_name: str) -> str:
    env_name = PROVIDER_ENV_KEYS.get(provider)
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    prompt = f"Enter provider API key for {provider} credential '{credential_name}' (blank to skip): "
    return getpass.getpass(prompt).strip()


def prompt_required_value(label: str, secret: bool = False, default: Optional[str] = None) -> str:
    prompt = f"{label}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    while True:
        value = getpass.getpass(prompt) if secret else input(prompt)
        value = value.strip()
        if not value and default is not None:
            value = default
        if value:
            return value
        print("Value is required.")


def resolve_runtime_config(args: argparse.Namespace) -> dict:
    env_n8n_base = os.environ.get("N8N_BASE_URL", "").strip()
    env_n8n_key = os.environ.get("N8N_API_KEY", "").strip()
    env_ascerta_base = os.environ.get("ASCERTA_BASE_URL", "").strip()
    env_ascerta_key = os.environ.get("ASCERTA_API_KEY", "").strip()

    n8n_base = (args.n8n_base_url or env_n8n_base).strip()
    n8n_key = (args.n8n_api_key or env_n8n_key).strip()
    ascerta_base = (args.ascerta_base_url or env_ascerta_base).strip()
    ascerta_key = (args.ascerta_api_key or env_ascerta_key).strip()

    if args.non_interactive:
        required = {"N8N_BASE_URL": n8n_base, "N8N_API_KEY": n8n_key}
        if args.configure_credentials:
            required["ASCERTA_BASE_URL"] = ascerta_base
            required["ASCERTA_API_KEY"] = ascerta_key
        missing = [k for k, v in required.items() if not v]
        if missing:
            print("ERROR: missing required inputs in non-interactive mode:")
            for key in missing:
                print(f"  - {key}")
            raise SystemExit(1)
    else:
        if not n8n_base:
            n8n_base = prompt_required_value("n8n base URL", default="http://localhost:5678")
        if not n8n_key:
            n8n_key = prompt_required_value("n8n API key", secret=True)
        if args.configure_credentials:
            if not ascerta_base:
                ascerta_base = prompt_required_value("Ascerta base URL", default="https://api.ascerta.com")
            if not ascerta_key:
                ascerta_key = prompt_required_value("Ascerta API key", secret=True)

    return {
        "n8n_base": n8n_base.rstrip("/"),
        "n8n_key": n8n_key,
        "ascerta_base": ascerta_base.rstrip("/") if ascerta_base else "",
        "ascerta_key": ascerta_key,
    }


def print_report(report: dict, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(report, indent=2))
        return

    summary = report["summary"]
    print()
    print("Ascerta Proxy Audit")
    print("=================")
    print(f"Workflows scanned: {summary['workflows_scanned']}")
    print(f"Tracked nodes found: {summary['tracked_nodes_found']}")
    providers = summary["provider_counts"]
    if providers:
        print("Providers / node types found:")
        for provider, count in sorted(providers.items()):
            print(f"  - {provider}: {count}")

    print()
    print("Node usage")
    print("----------")
    if not report["nodes"]:
        print("No known LLM or Ascerta nodes found.")
    for n in report["nodes"]:
        print(f"- [{n['workflow_name']}] {n['node_name']} ({n['label']})")
        print(f"  provider={n['provider']} source={n['source']} action={n['recommended_action']}")
        print(f"  incoming={len(n['incoming'])} outgoing={len(n['outgoing'])}")
        if n["expression_references"]:
            refs = ", ".join(f"{r['node']} x{r['count']}" for r in n["expression_references"])
            print(f"  referenced by expressions: {refs}")

    print()
    print("Credentials")
    print("-----------")
    if not report["credentials_usage"]:
        print("No credentials attached to matched nodes.")
    for cred_id, usage in sorted(report["credentials_usage"].items()):
        cred_type = usage.get("credential_type", "unknown")
        redirect_tag = usage.get("redirect_capability", "not_applicable")
        print(f"- [{cred_id}] {usage.get('n8n_credential_name', usage.get('credential_name', '?'))} ({cred_type}, {redirect_tag})")
        print(f"  used by {len(usage.get('used_by', []))} node(s)")

    manifest = report.get("migration_manifest", [])
    if manifest:
        path_counts: Dict[str, int] = {}
        for entry in manifest:
            path = entry.get("recommended_path", "unknown")
            path_counts[path] = path_counts.get(path, 0) + 1

        print()
        print("Migration Manifest")
        print("------------------")
        for path, count in sorted(path_counts.items()):
            print(f"  - {path}: {count}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit n8n workflow LLM usage and optionally configure Ascerta proxy credential redirects."
    )
    parser.add_argument("--from-json", metavar="PATH",
                        help="Load an existing JSON report and render/print without calling the n8n API")
    parser.add_argument("--n8n-base-url", metavar="URL",
                        help="n8n API base URL (fallback: N8N_BASE_URL)")
    parser.add_argument("--n8n-api-key", metavar="KEY",
                        help="n8n API key (fallback: N8N_API_KEY)")
    parser.add_argument("--ascerta-base-url", metavar="URL",
                        help="Ascerta base URL for credential patching (fallback: ASCERTA_BASE_URL)")
    parser.add_argument("--ascerta-api-key", metavar="KEY",
                        help="Ascerta API key for credential patching (fallback: ASCERTA_API_KEY)")
    parser.add_argument("--workflow", metavar="ID", help="Analyze only this workflow ID")
    parser.add_argument("--configure-credentials", action="store_true",
                        help="Patch redirectable credentials to Ascerta proxy URLs")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview credential changes without applying")
    parser.add_argument("--json", action="store_true", help="Print report as JSON")
    parser.add_argument("--report-format", choices=["json", "md"], default="json",
                        help="Format to use when writing --out (default: json)")
    parser.add_argument("--out", metavar="PATH", help="Write report to file (format controlled by --report-format)")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompts when configuring credentials")
    parser.add_argument("--verbose", action="store_true", help="Enable API call logging")
    parser.add_argument("--insecure", action="store_true",
                        help="Disable TLS verification (useful for local https://localhost certs)")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Disable prompts and fail if required inputs are missing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    client: Optional[N8nApiClient] = None
    ascerta_base = ""
    ascerta_key = ""

    if args.from_json:
        with open(args.from_json, "r", encoding="utf-8") as f:
            report = json.load(f)
    else:
        runtime = resolve_runtime_config(args)
        n8n_base = runtime["n8n_base"]
        n8n_key = runtime["n8n_key"]
        ascerta_base = runtime["ascerta_base"]
        ascerta_key = runtime["ascerta_key"]

        client = N8nApiClient(n8n_base, n8n_key, verbose=args.verbose, insecure=args.insecure)
        workflows = fetch_workflows(client, args.workflow)
        if not workflows:
            print("No workflows found for the selected scope.")
            return 0

        report = build_analysis_report(workflows)
        enrich_credentials_usage(client, report)
        report["migration_manifest"] = build_migration_manifest(report)

    print_report(report, as_json=args.json)

    if args.out:
        if args.report_format == "md":
            text = render_markdown_report(report)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
        print(f"\nWrote report: {args.out}")

    if not args.configure_credentials:
        return 0

    if client is None:
        print("ERROR: --configure-credentials cannot be used with --from-json")
        return 1

    selected = pick_credentials_for_redirect(report)
    if not selected:
        print("\nNo redirectable credentials found in the selected workflow scope.")
        return 0

    print("\nCredentials selected for Ascerta proxy redirect:")
    for c in selected:
        print(f"  - [{c['id']}] {c['credential_name']} ({c['provider']})")
    print()

    if not args.yes:
        answer = input("Apply these credential updates now? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted.")
            return 0

    updated = 0
    skipped = 0
    failed = 0
    for c in selected:
        provider_key = collect_provider_key(c["provider"], c["credential_name"])
        if not provider_key:
            print(f"SKIP [{c['id']}] {c['credential_name']} (no provider API key entered)")
            skipped += 1
            continue

        patch_data = build_patch_data(c["provider"], provider_key, ascerta_base, ascerta_key)
        if args.dry_run:
            print(f"DRY RUN [{c['id']}] {c['credential_name']} -> {c['provider']}")
            updated += 1
            continue

        try:
            client.patch(f"/api/v1/credentials/{c['id']}", patch_data)
            print(f"OK [{c['id']}] {c['credential_name']}")
            updated += 1
        except SystemExit:
            failed += 1

    print("\nCredential redirect summary")
    print("---------------------------")
    print(f"updated={updated} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
