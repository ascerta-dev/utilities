#!/usr/bin/env python3
"""
Tests for migrate-workflows-to-ascerta.py

Run:  python3 -m pytest test_migrate_workflows.py -v
  or: python3 test_migrate_workflows.py
"""

import argparse
import copy
import importlib.util
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ── Import the migration script as a module ──────────────────────────────────

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "migrate-workflows-to-ascerta.py")
spec = importlib.util.spec_from_file_location("migrate", SCRIPT_PATH)
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)

# ── Import the audit script as a module ──────────────────────────────────────

AUDIT_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "audit-configure-ascerta-proxy.py")
audit_spec = importlib.util.spec_from_file_location("audit_ascerta", AUDIT_SCRIPT_PATH)
audit_ascerta = importlib.util.module_from_spec(audit_spec)
audit_spec.loader.exec_module(audit_ascerta)

# ── Test Fixtures ────────────────────────────────────────────────────────────

ASCERTA_CRED = {"id": "cred-123", "name": "Ascerta API"}

OPENAI_CHAT_MODEL_NODE = {
    "id": "node-aaa",
    "name": "OpenAI Chat Model",
    "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
    "typeVersion": 1,
    "position": [400, 300],
    "parameters": {
        "model": "gpt-4.1-mini",
        "options": {
            "temperature": 0.5,
            "maxTokens": 2048,
            "topP": 0.9,
        },
    },
    "credentials": {
        "openAiApi": {"id": "old-cred", "name": "OpenAI"},
    },
}

OPENAI_APP_NODE = {
    "id": "node-bbb",
    "name": "OpenAI",
    "type": "@n8n/n8n-nodes-langchain.openai",
    "typeVersion": 1,
    "position": [600, 200],
    "parameters": {
        "model": "gpt-4o",
        "messages": '[{"role": "user", "content": "Summarize this"}]',
    },
    "credentials": {
        "openAiApi": {"id": "old-cred", "name": "OpenAI"},
    },
}

ANTHROPIC_CHAT_MODEL_NODE = {
    "id": "node-ccc",
    "name": "Anthropic Chat Model",
    "type": "@n8n/n8n-nodes-langchain.lmChatAnthropic",
    "typeVersion": 1,
    "position": [400, 500],
    "parameters": {"model": "claude-sonnet-4-20250514"},
}

ANTHROPIC_CHAT_MODEL_NODE_V12 = {
    "id": "node-ccc",
    "name": "Anthropic Chat Model",
    "type": "@n8n/n8n-nodes-langchain.lmChatAnthropic",
    "typeVersion": 1.2,
    "position": [400, 500],
    "parameters": {
        "options": {
            "maxTokensToSample": 8192,
            "temperature": 0.7,
        },
    },
    "credentials": {
        "anthropicApi": {
            "id": "cred-anthropic",
            "name": "Anthropic Account",
        },
    },
}

TRIGGER_NODE = {
    "id": "node-trigger",
    "name": "Manual Trigger",
    "type": "n8n-nodes-base.manualTrigger",
    "typeVersion": 1,
    "position": [200, 300],
    "parameters": {},
}

AGENT_NODE = {
    "id": "node-agent",
    "name": "AI Agent",
    "type": "@n8n/n8n-nodes-langchain.agent",
    "typeVersion": 1,
    "position": [600, 300],
    "parameters": {
        "text": "={{ $('OpenAI Chat Model').item.json.output }}",
        "other": "no refs here",
    },
}


def make_workflow(wf_id="wf-1", name="Test Workflow", nodes=None, connections=None):
    return {
        "id": wf_id,
        "name": name,
        "nodes": nodes or [],
        "connections": connections or {},
        "settings": {},
        "staticData": None,
        "pinData": {},
        # Read-only fields that GET returns
        "active": False,
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T00:00:00.000Z",
        "versionId": "v1",
        "tags": [],
    }


# ── Tests: find_llm_nodes ───────────────────────────────────────────────────

class TestFindLlmNodes(unittest.TestCase):
    def test_finds_openai_chat_model(self):
        wf = make_workflow(nodes=[TRIGGER_NODE, OPENAI_CHAT_MODEL_NODE])
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["provider"], "openai")
        self.assertEqual(found[0]["replacement"], "chat_model")
        self.assertTrue(found[0]["feasible"])

    def test_finds_openai_app_node(self):
        wf = make_workflow(nodes=[TRIGGER_NODE, OPENAI_APP_NODE])
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["replacement"], "proxy")
        self.assertTrue(found[0]["feasible"])

    def test_finds_anthropic_as_feasible(self):
        wf = make_workflow(nodes=[ANTHROPIC_CHAT_MODEL_NODE])
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["feasible"])
        self.assertEqual(found[0]["replacement"], "chat_model_anthropic")

    def test_ignores_non_llm_nodes(self):
        wf = make_workflow(nodes=[TRIGGER_NODE])
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 0)

    def test_multiple_workflows(self):
        wf1 = make_workflow("wf-1", "Bot A", [OPENAI_CHAT_MODEL_NODE])
        wf2 = make_workflow("wf-2", "Bot B", [OPENAI_APP_NODE, ANTHROPIC_CHAT_MODEL_NODE])
        found = migrate.find_llm_nodes([wf1, wf2])
        self.assertEqual(len(found), 3)
        feasible = [n for n in found if n["feasible"]]
        infeasible = [n for n in found if not n["feasible"]]
        self.assertEqual(len(feasible), 3)
        self.assertEqual(len(infeasible), 0)

    def test_preserves_workflow_metadata(self):
        wf = make_workflow("wf-42", "My Workflow", [OPENAI_CHAT_MODEL_NODE])
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(found[0]["workflow_id"], "wf-42")
        self.assertEqual(found[0]["workflow_name"], "My Workflow")

    def test_empty_workflows(self):
        found = migrate.find_llm_nodes([])
        self.assertEqual(len(found), 0)

    def test_workflow_with_no_nodes(self):
        wf = make_workflow(nodes=[])
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 0)

    def test_detects_all_infeasible_types(self):
        nodes = [
            {"name": "Gemini", "type": "@n8n/n8n-nodes-langchain.lmChatGoogleGemini", "parameters": {}},
            {"name": "Mistral", "type": "@n8n/n8n-nodes-langchain.lmChatMistralCloud", "parameters": {}},
        ]
        wf = make_workflow(nodes=nodes)
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 2)
        self.assertTrue(all(not n["feasible"] for n in found))

    def test_azure_and_bedrock_are_feasible(self):
        nodes = [
            {"name": "Azure", "type": "@n8n/n8n-nodes-langchain.lmChatAzureOpenAi", "parameters": {}},
            {"name": "Bedrock", "type": "@n8n/n8n-nodes-langchain.lmChatAwsBedrock", "parameters": {}},
        ]
        wf = make_workflow(nodes=nodes)
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 2)
        self.assertTrue(all(n["feasible"] for n in found))
        self.assertEqual(found[0]["replacement"], "chat_model_azure")
        self.assertEqual(found[1]["replacement"], "chat_model_bedrock")

    def test_databricks_shim_classified_separately(self):
        node = {
            "name": "DBX Shim",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "parameters": {
                "model": "databricks-llama-3-70b",
                "options": {"baseURL": "https://x.cloud.databricks.com/v1"},
            },
        }
        plain = {
            "name": "Plain OpenAI",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "parameters": {"model": "gpt-4o"},
        }
        wf = make_workflow(nodes=[node, plain])
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 2)

        shim = next(n for n in found if n["node"]["name"] == "DBX Shim")
        self.assertEqual(shim["replacement"], "chat_model_databricks")
        self.assertTrue(shim["feasible"])
        self.assertEqual(shim["databricks_shim"]["cloud_provider"], "aws")

        plain_found = next(n for n in found if n["node"]["name"] == "Plain OpenAI")
        self.assertEqual(plain_found["replacement"], "chat_model")
        self.assertNotIn("databricks_shim", plain_found)  # only set when shim


# ── Tests: build_ascerta_chat_model_node ────────────────────────────────────────

class TestBuildAscertaChatModelNode(unittest.TestCase):
    def test_basic_fields(self):
        result = migrate.build_ascerta_chat_model_node(
            OPENAI_CHAT_MODEL_NODE, ASCERTA_CRED, "sk-test-key", "Ascerta Chat Model"
        )
        self.assertEqual(result["type"], "@ascerta/n8n-nodes-ascerta.lmChatAscerta")
        self.assertEqual(result["name"], "Ascerta Chat Model")
        self.assertEqual(result["id"], "node-aaa")
        self.assertEqual(result["position"], [400, 300])
        self.assertEqual(result["typeVersion"], 1)

    def test_model_mapped(self):
        result = migrate.build_ascerta_chat_model_node(
            OPENAI_CHAT_MODEL_NODE, ASCERTA_CRED, "sk-test", "Ascerta Chat Model"
        )
        self.assertEqual(result["parameters"]["model"], "gpt-4.1-mini")

    def test_options_preserved(self):
        result = migrate.build_ascerta_chat_model_node(
            OPENAI_CHAT_MODEL_NODE, ASCERTA_CRED, "sk-test", "Ascerta Chat Model"
        )
        opts = result["parameters"]["options"]
        self.assertEqual(opts["temperature"], 0.5)
        self.assertEqual(opts["maxTokens"], 2048)
        self.assertEqual(opts["topP"], 0.9)

    def test_unsupported_options_excluded(self):
        node = copy.deepcopy(OPENAI_CHAT_MODEL_NODE)
        node["parameters"]["options"]["unknownOption"] = "foo"
        result = migrate.build_ascerta_chat_model_node(node, ASCERTA_CRED, "sk-test", "Ascerta Chat Model")
        self.assertNotIn("unknownOption", result["parameters"]["options"])

    def test_no_plaintext_provider_key(self):
        """providerApiKey should NOT be in parameters — credentials are passed through."""
        result = migrate.build_ascerta_chat_model_node(
            OPENAI_CHAT_MODEL_NODE, ASCERTA_CRED, "sk-my-key", "Ascerta Chat Model"
        )
        self.assertNotIn("providerApiKey", result["parameters"])

    def test_native_credential_passthrough(self):
        """The original node's openAiApi credential should be passed to the Ascerta node."""
        result = migrate.build_ascerta_chat_model_node(
            OPENAI_CHAT_MODEL_NODE, ASCERTA_CRED, "sk-test", "Ascerta Chat Model"
        )
        self.assertIn("openAiApi", result["credentials"])
        self.assertEqual(result["credentials"]["openAiApi"]["id"], "old-cred")
        self.assertEqual(result["credentials"]["openAiApi"]["name"], "OpenAI")

    def test_credentials_reference(self):
        result = migrate.build_ascerta_chat_model_node(
            OPENAI_CHAT_MODEL_NODE, ASCERTA_CRED, "sk-test", "Ascerta Chat Model"
        )
        cred_ref = result["credentials"]["ascertaApi"]
        self.assertEqual(cred_ref["id"], "cred-123")
        self.assertEqual(cred_ref["name"], "Ascerta API")

    def test_tracking_defaults(self):
        result = migrate.build_ascerta_chat_model_node(
            OPENAI_CHAT_MODEL_NODE, ASCERTA_CRED, "sk-test", "Ascerta Chat Model"
        )
        params = result["parameters"]
        self.assertEqual(params["useCaseName"], "={{ $workflow.name.replaceAll(' ', '-') }}")
        self.assertEqual(params["useCaseId"], "={{ 'openai/' + $parameter.model + '/' + $execution.id }}")
        self.assertEqual(params["useCaseStep"], "={{ $node.name }}")

    def test_default_model_when_missing(self):
        node = {"id": "x", "parameters": {}, "position": [0, 0]}
        result = migrate.build_ascerta_chat_model_node(node, ASCERTA_CRED, "sk-test", "Ascerta Chat Model")
        self.assertEqual(result["parameters"]["model"], "gpt-4o")

    def test_empty_options_when_none_in_source(self):
        node = {"id": "x", "parameters": {"model": "gpt-4o"}, "position": [0, 0]}
        result = migrate.build_ascerta_chat_model_node(node, ASCERTA_CRED, "sk-test", "Ascerta Chat Model")
        self.assertEqual(result["parameters"]["options"], {})

    def test_credential_id_stringified(self):
        cred = {"id": 42, "name": "Ascerta API"}
        result = migrate.build_ascerta_chat_model_node(
            OPENAI_CHAT_MODEL_NODE, cred, "sk-test", "Ascerta Chat Model"
        )
        self.assertEqual(result["credentials"]["ascertaApi"]["id"], "42")

    def test_model_from_resource_locator_object(self):
        """n8n 2.x stores model as resourceLocator: {mode, value}."""
        node = {
            "id": "x",
            "parameters": {
                "model": {"mode": "list", "value": "gpt-4.1-mini"},
                "options": {},
            },
            "position": [0, 0],
        }
        result = migrate.build_ascerta_chat_model_node(node, ASCERTA_CRED, "sk-test", "Ascerta Chat Model")
        self.assertEqual(result["parameters"]["model"], "gpt-4.1-mini")


# ── Tests: build_ascerta_proxy_node ─────────────────────────────────────────────

class TestBuildAscertaProxyNode(unittest.TestCase):
    def test_basic_fields(self):
        result = migrate.build_ascerta_proxy_node(
            OPENAI_APP_NODE, ASCERTA_CRED, "sk-test", "Ascerta Proxy"
        )
        self.assertEqual(result["type"], "@ascerta/n8n-nodes-ascerta.ascerta")
        self.assertEqual(result["name"], "Ascerta Proxy")
        self.assertEqual(result["id"], "node-bbb")
        self.assertEqual(result["position"], [600, 200])

    def test_model_mapped(self):
        result = migrate.build_ascerta_proxy_node(
            OPENAI_APP_NODE, ASCERTA_CRED, "sk-test", "Ascerta Proxy"
        )
        self.assertEqual(result["parameters"]["model"], "gpt-4o")
        self.assertEqual(result["parameters"]["provider"], "openai")

    def test_messages_json_string_preserved(self):
        result = migrate.build_ascerta_proxy_node(
            OPENAI_APP_NODE, ASCERTA_CRED, "sk-test", "Ascerta Proxy"
        )
        msgs = json.loads(result["parameters"]["messages"])
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["content"], "Summarize this")

    def test_messages_from_plain_prompt_string(self):
        node = copy.deepcopy(OPENAI_APP_NODE)
        node["parameters"] = {"model": "gpt-4o", "prompt": "Hello world"}
        result = migrate.build_ascerta_proxy_node(node, ASCERTA_CRED, "sk-test", "Ascerta Proxy")
        msgs = json.loads(result["parameters"]["messages"])
        self.assertEqual(msgs[0]["content"], "Hello world")

    def test_messages_from_list(self):
        node = copy.deepcopy(OPENAI_APP_NODE)
        node["parameters"]["messages"] = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
        ]
        result = migrate.build_ascerta_proxy_node(node, ASCERTA_CRED, "sk-test", "Ascerta Proxy")
        msgs = json.loads(result["parameters"]["messages"])
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")

    def test_messages_from_dict_values_format(self):
        node = copy.deepcopy(OPENAI_APP_NODE)
        node["parameters"]["messages"] = {
            "values": [
                {"role": "user", "content": "What is 2+2?"},
            ]
        }
        result = migrate.build_ascerta_proxy_node(node, ASCERTA_CRED, "sk-test", "Ascerta Proxy")
        msgs = json.loads(result["parameters"]["messages"])
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["content"], "What is 2+2?")

    def test_messages_empty_dict_values(self):
        node = copy.deepcopy(OPENAI_APP_NODE)
        node["parameters"]["messages"] = {"values": []}
        result = migrate.build_ascerta_proxy_node(node, ASCERTA_CRED, "sk-test", "Ascerta Proxy")
        msgs = json.loads(result["parameters"]["messages"])
        self.assertEqual(msgs[0]["content"], "Hello!")

    def test_messages_fallback_default(self):
        node = {"id": "x", "parameters": {"model": "gpt-4o"}, "position": [0, 0]}
        result = migrate.build_ascerta_proxy_node(node, ASCERTA_CRED, "sk-test", "Ascerta Proxy")
        msgs = json.loads(result["parameters"]["messages"])
        self.assertEqual(msgs[0]["content"], "Hello!")

    def test_output_defaults(self):
        result = migrate.build_ascerta_proxy_node(
            OPENAI_APP_NODE, ASCERTA_CRED, "sk-test", "Ascerta Proxy"
        )
        self.assertTrue(result["parameters"]["includeCostData"])
        self.assertFalse(result["parameters"]["returnFullResponse"])
        self.assertFalse(result["parameters"]["debugLogging"])

    def test_tracking_defaults(self):
        result = migrate.build_ascerta_proxy_node(
            OPENAI_APP_NODE, ASCERTA_CRED, "sk-test", "Ascerta Proxy"
        )
        self.assertEqual(result["parameters"]["useCaseName"], "={{ $workflow.name.replaceAll(' ', '-') }}")
        self.assertEqual(result["parameters"]["useCaseId"], "={{ 'openai/' + $parameter.model + '/' + $execution.id }}")
        self.assertEqual(result["parameters"]["useCaseStep"], "={{ $node.name }}")

    def test_model_from_resource_locator_object(self):
        """n8n 2.x stores model as resourceLocator: {mode, value}."""
        node = {
            "id": "x",
            "parameters": {
                "model": {"mode": "list", "value": "gpt-4o"},
                "messages": '[{"role": "user", "content": "Hi"}]',
            },
            "position": [0, 0],
        }
        result = migrate.build_ascerta_proxy_node(node, ASCERTA_CRED, "sk-test", "Ascerta Proxy")
        self.assertEqual(result["parameters"]["model"], "gpt-4o")


# ── Tests: build_ascerta_chat_model_anthropic_node ──────────────────────────────

class TestBuildAscertaChatModelAnthropicNode(unittest.TestCase):
    def test_basic_fields(self):
        result = migrate.build_ascerta_chat_model_anthropic_node(
            ANTHROPIC_CHAT_MODEL_NODE_V12, ASCERTA_CRED, "sk-ant-test", "Ascerta Anthropic Chat Model"
        )
        self.assertEqual(result["id"], "node-ccc")
        self.assertEqual(result["name"], "Ascerta Anthropic Chat Model")
        self.assertEqual(result["type"], "@ascerta/n8n-nodes-ascerta.lmChatAscertaAnthropic")
        self.assertEqual(result["typeVersion"], 1)
        self.assertEqual(result["position"], [400, 500])

    def test_model_extraction(self):
        """Default model when none specified should be empty string."""
        node = {"id": "x", "parameters": {}, "position": [0, 0]}
        result = migrate.build_ascerta_chat_model_anthropic_node(node, ASCERTA_CRED, "sk-ant-test", "Ascerta Anthropic Chat Model")
        self.assertEqual(result["parameters"]["model"], "")

    def test_model_from_resource_locator(self):
        """Handle resourceLocator dict format for model."""
        node = {
            "id": "x",
            "parameters": {
                "model": {"mode": "list", "value": "claude-sonnet-4-20250514"},
                "options": {},
            },
            "position": [0, 0],
        }
        result = migrate.build_ascerta_chat_model_anthropic_node(node, ASCERTA_CRED, "sk-ant-test", "Ascerta Anthropic Chat Model")
        self.assertEqual(result["parameters"]["model"], "claude-sonnet-4-20250514")

    def test_options_mapping(self):
        """maxTokensToSample, temperature, topK, topP are mapped correctly."""
        node = {
            "id": "x",
            "parameters": {
                "model": "claude-sonnet-4-20250514",
                "options": {
                    "maxTokensToSample": 4096,
                    "temperature": 0.8,
                    "topK": 40,
                    "topP": 0.95,
                },
            },
            "position": [0, 0],
        }
        result = migrate.build_ascerta_chat_model_anthropic_node(node, ASCERTA_CRED, "sk-ant-test", "Ascerta Anthropic Chat Model")
        opts = result["parameters"]["options"]
        self.assertEqual(opts["maxTokensToSample"], 4096)
        self.assertEqual(opts["temperature"], 0.8)
        self.assertEqual(opts["topK"], 40)
        self.assertEqual(opts["topP"], 0.95)

    def test_thinking_mode_options(self):
        """When source has thinking and thinkingBudget, these are preserved."""
        node = {
            "id": "x",
            "parameters": {
                "model": "claude-sonnet-4-20250514",
                "options": {
                    "thinking": True,
                    "thinkingBudget": 10000,
                },
            },
            "position": [0, 0],
        }
        result = migrate.build_ascerta_chat_model_anthropic_node(node, ASCERTA_CRED, "sk-ant-test", "Ascerta Anthropic Chat Model")
        opts = result["parameters"]["options"]
        self.assertTrue(opts["thinking"])
        self.assertEqual(opts["thinkingBudget"], 10000)

    def test_empty_options(self):
        """When source has no options, result has empty options dict."""
        node = {"id": "x", "parameters": {"model": "claude-sonnet-4-20250514"}, "position": [0, 0]}
        result = migrate.build_ascerta_chat_model_anthropic_node(node, ASCERTA_CRED, "sk-ant-test", "Ascerta Anthropic Chat Model")
        self.assertEqual(result["parameters"]["options"], {})

    def test_credential_reference(self):
        """ascertaApi credential is set correctly."""
        result = migrate.build_ascerta_chat_model_anthropic_node(
            ANTHROPIC_CHAT_MODEL_NODE_V12, ASCERTA_CRED, "sk-ant-test", "Ascerta Anthropic Chat Model"
        )
        cred_ref = result["credentials"]["ascertaApi"]
        self.assertEqual(cred_ref["id"], "cred-123")
        self.assertEqual(cred_ref["name"], "Ascerta API")

    def test_tracking_defaults(self):
        """useCaseName and useCaseId expressions are set."""
        result = migrate.build_ascerta_chat_model_anthropic_node(
            ANTHROPIC_CHAT_MODEL_NODE_V12, ASCERTA_CRED, "sk-ant-test", "Ascerta Anthropic Chat Model"
        )
        params = result["parameters"]
        self.assertEqual(params["useCaseName"], "={{ $workflow.name.replaceAll(' ', '-') }}")
        self.assertEqual(params["useCaseId"], "={{ 'anthropic/' + $parameter.model + '/' + $execution.id }}")
        self.assertEqual(params["useCaseStep"], "={{ $node.name }}")

    def test_no_plaintext_provider_key(self):
        """providerApiKey should NOT be in parameters — credentials are passed through."""
        result = migrate.build_ascerta_chat_model_anthropic_node(
            ANTHROPIC_CHAT_MODEL_NODE_V12, ASCERTA_CRED, "sk-ant-my-key", "Ascerta Anthropic Chat Model"
        )
        self.assertNotIn("providerApiKey", result["parameters"])

    def test_credential_id_stringified(self):
        cred = {"id": 99, "name": "Ascerta API"}
        result = migrate.build_ascerta_chat_model_anthropic_node(
            ANTHROPIC_CHAT_MODEL_NODE_V12, cred, "sk-ant-test", "Ascerta Anthropic Chat Model"
        )
        self.assertEqual(result["credentials"]["ascertaApi"]["id"], "99")

    def test_model_string_preserved(self):
        """Model specified as a plain string is preserved."""
        result = migrate.build_ascerta_chat_model_anthropic_node(
            ANTHROPIC_CHAT_MODEL_NODE, ASCERTA_CRED, "sk-ant-test", "Ascerta Anthropic Chat Model"
        )
        self.assertEqual(result["parameters"]["model"], "claude-sonnet-4-20250514")

    def test_unknown_options_excluded(self):
        """Options not in the Anthropic allowlist are excluded."""
        node = {
            "id": "x",
            "parameters": {
                "model": "claude-sonnet-4-20250514",
                "options": {
                    "temperature": 0.5,
                    "unknownOption": "foo",
                    "frequencyPenalty": 0.1,
                },
            },
            "position": [0, 0],
        }
        result = migrate.build_ascerta_chat_model_anthropic_node(node, ASCERTA_CRED, "sk-ant-test", "Ascerta Anthropic Chat Model")
        opts = result["parameters"]["options"]
        self.assertIn("temperature", opts)
        self.assertNotIn("unknownOption", opts)
        self.assertNotIn("frequencyPenalty", opts)


# ── Tests: unique_node_name ──────────────────────────────────────────────────

class TestUniqueNodeName(unittest.TestCase):
    def test_no_collision(self):
        self.assertEqual(
            migrate.unique_node_name("Ascerta Chat Model", {"Trigger", "Agent"}),
            "Ascerta Chat Model",
        )

    def test_collision_adds_suffix(self):
        self.assertEqual(
            migrate.unique_node_name("Ascerta Chat Model", {"Ascerta Chat Model", "Agent"}),
            "Ascerta Chat Model 1",
        )

    def test_multiple_collisions(self):
        existing = {"Ascerta Chat Model", "Ascerta Chat Model 1", "Ascerta Chat Model 2"}
        self.assertEqual(
            migrate.unique_node_name("Ascerta Chat Model", existing),
            "Ascerta Chat Model 3",
        )

    def test_empty_set(self):
        self.assertEqual(migrate.unique_node_name("Foo", set()), "Foo")


# ── Tests: rewire_connections ────────────────────────────────────────────────

class TestRewireConnections(unittest.TestCase):
    def test_renames_source_key(self):
        connections = {
            "OpenAI Chat Model": {
                "ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]
            },
        }
        result = migrate.rewire_connections(connections, "OpenAI Chat Model", "Ascerta Chat Model")
        self.assertIn("Ascerta Chat Model", result)
        self.assertNotIn("OpenAI Chat Model", result)

    def test_renames_target_reference(self):
        connections = {
            "Trigger": {
                "main": [[{"node": "OpenAI Chat Model", "type": "main", "index": 0}]]
            },
        }
        result = migrate.rewire_connections(connections, "OpenAI Chat Model", "Ascerta Chat Model")
        target = result["Trigger"]["main"][0][0]
        self.assertEqual(target["node"], "Ascerta Chat Model")

    def test_renames_both_source_and_target(self):
        connections = {
            "OpenAI Chat Model": {
                "ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]
            },
            "Trigger": {
                "main": [[{"node": "OpenAI Chat Model", "type": "main", "index": 0}]]
            },
        }
        result = migrate.rewire_connections(connections, "OpenAI Chat Model", "Ascerta Chat Model")
        self.assertIn("Ascerta Chat Model", result)
        self.assertNotIn("OpenAI Chat Model", result)
        self.assertEqual(result["Trigger"]["main"][0][0]["node"], "Ascerta Chat Model")

    def test_no_change_when_names_equal(self):
        connections = {"Foo": {"main": [[{"node": "Bar", "type": "main", "index": 0}]]}}
        result = migrate.rewire_connections(connections, "Foo", "Foo")
        self.assertIs(result, connections)  # same object, no copy

    def test_other_nodes_untouched(self):
        connections = {
            "Trigger": {
                "main": [[
                    {"node": "OpenAI", "type": "main", "index": 0},
                    {"node": "Logger", "type": "main", "index": 1},
                ]]
            },
        }
        result = migrate.rewire_connections(connections, "OpenAI", "Ascerta Proxy")
        slot = result["Trigger"]["main"][0]
        self.assertEqual(slot[0]["node"], "Ascerta Proxy")
        self.assertEqual(slot[1]["node"], "Logger")  # untouched

    def test_empty_connections(self):
        result = migrate.rewire_connections({}, "Old", "New")
        self.assertEqual(result, {})

    def test_multiple_connection_types(self):
        connections = {
            "OpenAI Chat Model": {
                "ai_languageModel": [[{"node": "Agent", "type": "ai_languageModel", "index": 0}]],
                "main": [[{"node": "Output", "type": "main", "index": 0}]],
            },
        }
        result = migrate.rewire_connections(connections, "OpenAI Chat Model", "Ascerta Chat Model")
        self.assertIn("ai_languageModel", result["Ascerta Chat Model"])
        self.assertIn("main", result["Ascerta Chat Model"])

    def test_multiple_slots(self):
        connections = {
            "Router": {
                "main": [
                    [{"node": "OpenAI", "type": "main", "index": 0}],
                    [{"node": "Logger", "type": "main", "index": 0}],
                ]
            },
        }
        result = migrate.rewire_connections(connections, "OpenAI", "Ascerta Proxy")
        self.assertEqual(result["Router"]["main"][0][0]["node"], "Ascerta Proxy")
        self.assertEqual(result["Router"]["main"][1][0]["node"], "Logger")


# ── Tests: fix_expression_references ─────────────────────────────────────────

class TestFixExpressionReferences(unittest.TestCase):
    def test_replaces_single_quote_reference(self):
        nodes = [{"parameters": {"text": "={{ $('OpenAI Chat Model').item.json.output }}"}}]
        count = migrate.fix_expression_references(nodes, "OpenAI Chat Model", "Ascerta Chat Model")
        self.assertEqual(count, 1)
        self.assertIn("Ascerta Chat Model", nodes[0]["parameters"]["text"])
        self.assertNotIn("OpenAI Chat Model", nodes[0]["parameters"]["text"])

    def test_replaces_double_quote_reference(self):
        nodes = [{"parameters": {"text": '={{ $("OpenAI Chat Model").item.json }}'}}]
        count = migrate.fix_expression_references(nodes, "OpenAI Chat Model", "Ascerta Chat Model")
        self.assertEqual(count, 1)
        self.assertIn("Ascerta Chat Model", nodes[0]["parameters"]["text"])

    def test_no_change_when_no_references(self):
        nodes = [{"parameters": {"text": "hello world"}}]
        count = migrate.fix_expression_references(nodes, "OpenAI Chat Model", "Ascerta Chat Model")
        self.assertEqual(count, 0)
        self.assertEqual(nodes[0]["parameters"]["text"], "hello world")

    def test_no_change_when_names_equal(self):
        nodes = [{"parameters": {"text": "={{ $('Foo').item }}"}}]
        count = migrate.fix_expression_references(nodes, "Foo", "Foo")
        self.assertEqual(count, 0)

    def test_nested_dict_parameters(self):
        nodes = [{"parameters": {"outer": {"inner": "={{ $('Old').item }}"}}}]
        count = migrate.fix_expression_references(nodes, "Old", "New")
        self.assertEqual(count, 1)
        self.assertEqual(nodes[0]["parameters"]["outer"]["inner"], "={{ $('New').item }}")

    def test_list_parameters(self):
        nodes = [{"parameters": {"items": ["={{ $('Old').item }}", "no ref"]}}]
        count = migrate.fix_expression_references(nodes, "Old", "New")
        self.assertEqual(count, 1)
        self.assertEqual(nodes[0]["parameters"]["items"][0], "={{ $('New').item }}")
        self.assertEqual(nodes[0]["parameters"]["items"][1], "no ref")

    def test_multiple_references_in_one_string(self):
        nodes = [{"parameters": {"text": "={{ $('Old').a }} + {{ $('Old').b }}"}}]
        count = migrate.fix_expression_references(nodes, "Old", "New")
        # count is 1 because replace_in_value counts per string, not per match
        self.assertEqual(count, 1)
        self.assertNotIn("Old", nodes[0]["parameters"]["text"])

    def test_multiple_nodes_with_references(self):
        nodes = [
            {"parameters": {"text": "={{ $('Old').item }}"}},
            {"parameters": {"other": "={{ $('Old').data }}"}},
            {"parameters": {"clean": "no ref"}},
        ]
        count = migrate.fix_expression_references(nodes, "Old", "New")
        self.assertEqual(count, 2)

    def test_skips_nodes_without_parameters(self):
        nodes = [{"name": "Trigger"}]  # no 'parameters' key
        count = migrate.fix_expression_references(nodes, "Old", "New")
        self.assertEqual(count, 0)

    def test_non_string_values_unchanged(self):
        nodes = [{"parameters": {"count": 42, "flag": True, "nothing": None}}]
        count = migrate.fix_expression_references(nodes, "Old", "New")
        self.assertEqual(count, 0)
        self.assertEqual(nodes[0]["parameters"]["count"], 42)


# ── Tests: filter_workflow_for_update ────────────────────────────────────────

class TestFilterWorkflowForUpdate(unittest.TestCase):
    def test_strips_read_only_fields(self):
        wf = make_workflow()
        filtered = migrate.filter_workflow_for_update(wf)
        for field in ("id", "active", "createdAt", "updatedAt", "versionId", "tags"):
            self.assertNotIn(field, filtered)

    def test_keeps_required_fields(self):
        wf = make_workflow(nodes=[TRIGGER_NODE])
        filtered = migrate.filter_workflow_for_update(wf)
        self.assertIn("name", filtered)
        self.assertIn("nodes", filtered)
        self.assertIn("connections", filtered)
        self.assertIn("settings", filtered)

    def test_strips_non_allowed_top_level_fields(self):
        wf = make_workflow()
        wf["customField"] = "drop me"
        wf["triggerCount"] = 5
        wf["meta"] = {"some": "data"}
        filtered = migrate.filter_workflow_for_update(wf)
        for field in ("customField", "triggerCount", "meta", "staticData", "pinData"):
            self.assertNotIn(field, filtered)

    def test_sanitizes_settings_keys(self):
        wf = make_workflow()
        wf["settings"] = {
            "executionOrder": "v1",
            "saveManualExecutions": True,
            "unknownSetting": "drop me",
        }
        filtered = migrate.filter_workflow_for_update(wf)
        self.assertIn("executionOrder", filtered["settings"])
        self.assertIn("saveManualExecutions", filtered["settings"])
        self.assertNotIn("unknownSetting", filtered["settings"])

    def test_strips_unknown_fields(self):
        wf = make_workflow()
        wf["customField"] = "drop me"
        wf["triggerCount"] = 5
        wf["meta"] = {"some": "data"}
        filtered = migrate.filter_workflow_for_update(wf)
        self.assertNotIn("customField", filtered)
        self.assertNotIn("triggerCount", filtered)
        self.assertNotIn("meta", filtered)


# ── Tests: _redact_dict ─────────────────────────────────────────────────────

class TestRedactDict(unittest.TestCase):
    def test_redacts_apikey(self):
        result = migrate._redact_dict({"apiKey": "sk-secret123"})
        self.assertEqual(result["apiKey"], "****")

    def test_redacts_password(self):
        result = migrate._redact_dict({"password": "p@ss"})
        self.assertEqual(result["password"], "****")

    def test_preserves_safe_values(self):
        result = migrate._redact_dict({"name": "My Cred", "baseUrl": "https://example.com"})
        self.assertEqual(result["name"], "My Cred")
        self.assertEqual(result["baseUrl"], "https://example.com")

    def test_nested_dict_redaction(self):
        result = migrate._redact_dict({"data": {"apiKey": "secret", "url": "https://x.com"}})
        self.assertEqual(result["data"]["apiKey"], "****")
        self.assertEqual(result["data"]["url"], "https://x.com")


# ── Tests: ensure_ascerta_credential ────────────────────────────────────────────

class TestEnsureAscertaCredential(unittest.TestCase):
    def test_finds_existing_credential(self):
        client = MagicMock()
        client.get.return_value = {
            "data": [
                {"id": "c-1", "name": "OpenAI", "type": "openAiApi"},
                {"id": "c-2", "name": "Ascerta API", "type": "ascertaApi"},
            ]
        }
        result = migrate.ensure_ascerta_credential(client, "pk-test", "https://api.ascerta.com")
        self.assertEqual(result["id"], "c-2")
        self.assertEqual(result["name"], "Ascerta API")
        client.post.assert_not_called()

    def test_creates_credential_when_missing(self):
        client = MagicMock()
        client.get.return_value = {
            "data": [
                {"id": "c-1", "name": "OpenAI", "type": "openAiApi"},
            ]
        }
        client.post.return_value = {"id": "c-new", "name": "Ascerta API", "type": "ascertaApi"}
        result = migrate.ensure_ascerta_credential(client, "pk-test", "https://api.ascerta.com")
        self.assertEqual(result["id"], "c-new")
        client.post.assert_called_once()
        call_body = client.post.call_args[0][1]
        self.assertEqual(call_body["type"], "ascertaApi")
        self.assertEqual(call_body["data"]["apiKey"], "pk-test")
        self.assertEqual(call_body["data"]["baseUrl"], "https://api.ascerta.com")

    def test_handles_empty_credentials_list(self):
        client = MagicMock()
        client.get.return_value = {"data": []}
        client.post.return_value = {"id": "c-new"}
        result = migrate.ensure_ascerta_credential(client, "pk-test", "https://api.ascerta.com")
        self.assertEqual(result["id"], "c-new")
        client.post.assert_called_once()


# ── Tests: collect_provider_keys ─────────────────────────────────────────────

class TestCollectProviderKeys(unittest.TestCase):
    def test_reads_from_env(self):
        nodes = [{"feasible": True, "provider": "openai"}]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-env"}):
            keys = migrate.collect_provider_keys(nodes)
        self.assertEqual(keys["openai"], "sk-from-env")

    def test_prompts_when_no_env(self):
        nodes = [{"feasible": True, "provider": "openai"}]
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with patch.object(migrate.getpass, "getpass", return_value="sk-interactive"):
                keys = migrate.collect_provider_keys(nodes)
        self.assertEqual(keys["openai"], "sk-interactive")

    def test_skips_empty_key(self):
        nodes = [{"feasible": True, "provider": "openai"}]
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with patch.object(migrate.getpass, "getpass", return_value=""):
                keys = migrate.collect_provider_keys(nodes)
        self.assertNotIn("openai", keys)

    def test_ignores_infeasible_nodes(self):
        nodes = [
            {"feasible": False, "provider": "google"},
            {"feasible": True, "provider": "openai"},
        ]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            keys = migrate.collect_provider_keys(nodes)
        self.assertIn("openai", keys)
        self.assertNotIn("google", keys)

    def test_deduplicates_providers(self):
        nodes = [
            {"feasible": True, "provider": "openai"},
            {"feasible": True, "provider": "openai"},
        ]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            keys = migrate.collect_provider_keys(nodes)
        self.assertEqual(len(keys), 1)


# ── Tests: End-to-End (main with mocked API) ────────────────────────────────

class TestMainDryRun(unittest.TestCase):
    """Test the main() function in dry-run mode with mocked API calls."""

    def _make_env(self):
        return {
            "N8N_BASE_URL": "http://localhost:5678",
            "N8N_API_KEY": "test-key",
            "ASCERTA_BASE_URL": "https://api.ascerta.com",
            "ASCERTA_API_KEY": "pk-test",
        }

    def test_dry_run_detects_and_reports(self):
        workflow = make_workflow(
            "wf-1", "Test Bot",
            nodes=[TRIGGER_NODE, OPENAI_CHAT_MODEL_NODE, AGENT_NODE],
            connections={
                "OpenAI Chat Model": {
                    "ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]
                },
            },
        )

        with patch.dict(os.environ, self._make_env(), clear=False):
            with patch("sys.argv", ["migrate", "--dry-run", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request") as mock_req:
                    mock_req.side_effect = lambda method, path, body=None, quiet=False: {
                        ("/api/v1/workflows", "GET"): {"data": [workflow]},
                        (f"/api/v1/workflows/wf-1", "GET"): workflow,
                    }.get((path, method), {})

                    rc = migrate.main()

        self.assertEqual(rc, 0)

    def test_missing_env_returns_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.argv", ["migrate"]):
                rc = migrate.main()
        self.assertEqual(rc, 1)

    def test_no_workflows_returns_zero(self):
        with patch.dict(os.environ, self._make_env(), clear=False):
            with patch("sys.argv", ["migrate", "--dry-run", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request") as mock_req:
                    mock_req.return_value = {"data": []}
                    rc = migrate.main()
        self.assertEqual(rc, 0)

    def test_no_llm_nodes_returns_zero(self):
        workflow = make_workflow("wf-1", "Clean Bot", nodes=[TRIGGER_NODE])
        with patch.dict(os.environ, self._make_env(), clear=False):
            with patch("sys.argv", ["migrate", "--dry-run", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request") as mock_req:
                    mock_req.return_value = {"data": [workflow]}
                    rc = migrate.main()
        self.assertEqual(rc, 0)

    def test_only_infeasible_nodes_returns_zero(self):
        azure_node = {
            "id": "node-azure",
            "name": "Azure OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatAzureOpenAi",
            "typeVersion": 1,
            "position": [400, 500],
            "parameters": {"model": "gpt-4o"},
        }
        workflow = make_workflow("wf-1", "Azure Bot", nodes=[azure_node])
        with patch.dict(os.environ, self._make_env(), clear=False):
            with patch("sys.argv", ["migrate", "--dry-run", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request") as mock_req:
                    mock_req.return_value = {"data": [workflow]}
                    rc = migrate.main()
        self.assertEqual(rc, 0)


class TestMainFullMigration(unittest.TestCase):
    """Test the main() function in full mode with mocked API and auto-yes."""

    def _make_env(self):
        return {
            "N8N_BASE_URL": "http://localhost:5678",
            "N8N_API_KEY": "test-key",
            "ASCERTA_BASE_URL": "https://api.ascerta.com",
            "ASCERTA_API_KEY": "pk-test",
            "OPENAI_API_KEY": "sk-from-env",
        }

    def test_full_migration_chat_model(self):
        """End-to-end: OpenAI Chat Model -> Ascerta Chat Model with auto-yes."""
        workflow = make_workflow(
            "wf-1", "Test Bot",
            nodes=[TRIGGER_NODE, copy.deepcopy(OPENAI_CHAT_MODEL_NODE), copy.deepcopy(AGENT_NODE)],
            connections={
                "OpenAI Chat Model": {
                    "ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]
                },
            },
        )

        put_calls = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET" and path == "/api/v1/workflows":
                return {"data": [workflow]}
            if method == "GET" and path == "/api/v1/workflows/wf-1":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": [{"id": "c-1", "name": "Ascerta API", "type": "ascertaApi"}]}
            if method == "PUT":
                put_calls.append({"path": path, "body": body})
                return {}
            return {}

        with patch.dict(os.environ, self._make_env(), clear=False):
            with patch("sys.argv", ["migrate", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        # Verify a PUT was issued
        self.assertEqual(len(put_calls), 1)
        put_body = put_calls[0]["body"]

        # Verify the node was replaced
        node_types = [n["type"] for n in put_body["nodes"]]
        self.assertIn("@ascerta/n8n-nodes-ascerta.lmChatAscerta", node_types)
        self.assertNotIn("@n8n/n8n-nodes-langchain.lmChatOpenAi", node_types)

        # Verify connections were rewired
        self.assertIn("Ascerta Chat Model", put_body["connections"])
        self.assertNotIn("OpenAI Chat Model", put_body["connections"])

        # Verify read-only fields stripped
        self.assertNotIn("id", put_body)
        self.assertNotIn("active", put_body)
        self.assertNotIn("createdAt", put_body)

    def test_full_migration_proxy_node(self):
        """End-to-end: OpenAI app node -> Ascerta Proxy with auto-yes."""
        workflow = make_workflow(
            "wf-2", "Data Pipeline",
            nodes=[TRIGGER_NODE, copy.deepcopy(OPENAI_APP_NODE)],
            connections={
                "Manual Trigger": {
                    "main": [[{"node": "OpenAI", "type": "main", "index": 0}]]
                },
            },
        )

        put_calls = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET" and path == "/api/v1/workflows":
                return {"data": [workflow]}
            if method == "GET" and path == "/api/v1/workflows/wf-2":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": [{"id": "c-1", "name": "Ascerta API", "type": "ascertaApi"}]}
            if method == "PUT":
                put_calls.append({"path": path, "body": body})
                return {}
            return {}

        with patch.dict(os.environ, self._make_env(), clear=False):
            with patch("sys.argv", ["migrate", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(put_calls), 1)
        put_body = put_calls[0]["body"]

        node_types = [n["type"] for n in put_body["nodes"]]
        self.assertIn("@ascerta/n8n-nodes-ascerta.ascerta", node_types)
        self.assertNotIn("@n8n/n8n-nodes-langchain.openai", node_types)

        # Verify connection target was renamed
        trigger_conns = put_body["connections"]["Manual Trigger"]["main"][0]
        self.assertEqual(trigger_conns[0]["node"], "Ascerta Proxy")

    def test_full_migration_anthropic_chat_model(self):
        """End-to-end: Anthropic Chat Model -> Ascerta Anthropic Chat Model with auto-yes."""
        anthropic_node = copy.deepcopy(ANTHROPIC_CHAT_MODEL_NODE_V12)
        agent = copy.deepcopy(AGENT_NODE)
        agent["parameters"]["text"] = "={{ $('Anthropic Chat Model').item.json.output }}"
        workflow = make_workflow(
            "wf-3", "Anthropic Bot",
            nodes=[TRIGGER_NODE, anthropic_node, agent],
            connections={
                "Anthropic Chat Model": {
                    "ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]
                },
            },
        )

        put_calls = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET" and path == "/api/v1/workflows":
                return {"data": [workflow]}
            if method == "GET" and path == "/api/v1/workflows/wf-3":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": [{"id": "c-1", "name": "Ascerta API", "type": "ascertaApi"}]}
            if method == "PUT":
                put_calls.append({"path": path, "body": body})
                return {}
            return {}

        env = {**self._make_env(), "ANTHROPIC_API_KEY": "sk-ant-test"}
        with patch.dict(os.environ, env, clear=False):
            with patch("sys.argv", ["migrate", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        # Verify a PUT was issued
        self.assertEqual(len(put_calls), 1)
        put_body = put_calls[0]["body"]

        # Verify the node was replaced with Anthropic Ascerta type
        node_types = [n["type"] for n in put_body["nodes"]]
        self.assertIn("@ascerta/n8n-nodes-ascerta.lmChatAscertaAnthropic", node_types)
        self.assertNotIn("@n8n/n8n-nodes-langchain.lmChatAnthropic", node_types)

        # Verify connections were rewired
        self.assertIn("Ascerta Anthropic Chat Model", put_body["connections"])
        self.assertNotIn("Anthropic Chat Model", put_body["connections"])

        # Verify expression references were updated
        agent_node = next(n for n in put_body["nodes"] if n["name"] == "AI Agent")
        self.assertIn("Ascerta Anthropic Chat Model", agent_node["parameters"]["text"])
        # The old bare name should not appear — check by ensuring the only occurrence
        # of "Anthropic Chat Model" is prefixed with "Ascerta "
        self.assertNotIn("$('Anthropic Chat Model')", agent_node["parameters"]["text"])

        # Verify read-only fields stripped
        self.assertNotIn("id", put_body)
        self.assertNotIn("active", put_body)

    def test_expression_references_fixed_in_full_migration(self):
        """Verify $('OpenAI Chat Model') references are updated."""
        agent = copy.deepcopy(AGENT_NODE)
        workflow = make_workflow(
            "wf-1", "Ref Test",
            nodes=[TRIGGER_NODE, copy.deepcopy(OPENAI_CHAT_MODEL_NODE), agent],
            connections={
                "OpenAI Chat Model": {
                    "ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]
                },
            },
        )

        put_calls = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET" and path == "/api/v1/workflows":
                return {"data": [workflow]}
            if method == "GET" and path == "/api/v1/workflows/wf-1":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": [{"id": "c-1", "name": "Ascerta API", "type": "ascertaApi"}]}
            if method == "PUT":
                put_calls.append({"path": path, "body": body})
                return {}
            return {}

        with patch.dict(os.environ, self._make_env(), clear=False):
            with patch("sys.argv", ["migrate", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        put_body = put_calls[0]["body"]

        # Find the agent node and check its expression was updated
        agent_node = next(n for n in put_body["nodes"] if n["name"] == "AI Agent")
        self.assertIn("Ascerta Chat Model", agent_node["parameters"]["text"])
        self.assertNotIn("OpenAI Chat Model", agent_node["parameters"]["text"])

    def test_creates_credential_when_missing(self):
        """Verify credential creation when no ascertaApi exists."""
        workflow = make_workflow(
            "wf-1", "Test",
            nodes=[TRIGGER_NODE, copy.deepcopy(OPENAI_CHAT_MODEL_NODE)],
            connections={},
        )
        post_calls = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET" and path == "/api/v1/workflows":
                return {"data": [workflow]}
            if method == "GET" and path == "/api/v1/workflows/wf-1":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": []}  # No credentials
            if method == "POST" and path == "/api/v1/credentials":
                post_calls.append(body)
                return {"id": "c-new", "name": "Ascerta API"}
            if method == "PUT":
                return {}
            return {}

        with patch.dict(os.environ, self._make_env(), clear=False):
            with patch("sys.argv", ["migrate", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(post_calls), 1)
        self.assertEqual(post_calls[0]["type"], "ascertaApi")

    def test_workflow_filter_flag(self):
        """Verify --workflow ID only fetches that one workflow."""
        workflow = make_workflow(
            "wf-99", "Target",
            nodes=[TRIGGER_NODE, copy.deepcopy(OPENAI_CHAT_MODEL_NODE)],
            connections={},
        )

        get_paths = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET":
                get_paths.append(path)
            if method == "GET" and path == "/api/v1/workflows/wf-99":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": [{"id": "c-1", "name": "Ascerta API", "type": "ascertaApi"}]}
            if method == "PUT":
                return {}
            return {}

        with patch.dict(os.environ, self._make_env(), clear=False):
            with patch("sys.argv", ["migrate", "--auto-yes", "--workflow", "wf-99"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        # Should NOT have called /api/v1/workflows (list all)
        self.assertNotIn("/api/v1/workflows", get_paths)
        self.assertIn("/api/v1/workflows/wf-99", get_paths)


# ── Tests: N8nApiClient ─────────────────────────────────────────────────────

class TestN8nApiClient(unittest.TestCase):
    def test_strips_trailing_slash(self):
        client = migrate.N8nApiClient("http://localhost:5678/", "key")
        self.assertEqual(client.base_url, "http://localhost:5678")

    def test_sets_headers(self):
        client = migrate.N8nApiClient("http://localhost:5678", "my-api-key")
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"ok": true}'
            mock_resp.status = 200
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            client.get("/api/v1/test")

            req = mock_open.call_args[0][0]
            self.assertEqual(req.get_header("X-n8n-api-key"), "my-api-key")
            self.assertEqual(req.get_header("Content-type"), "application/json")
            self.assertEqual(req.get_header("Accept"), "application/json")


# ── Tests: Edge Cases ────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    def test_name_collision_during_migration(self):
        """If 'Ascerta Chat Model' already exists, suffix should be added."""
        existing_ascerta_node = {
            "id": "node-existing",
            "name": "Ascerta Chat Model",
            "type": "@ascerta/n8n-nodes-ascerta.lmChatAscerta",
            "typeVersion": 1,
            "position": [200, 200],
            "parameters": {},
        }
        workflow = make_workflow(
            "wf-1", "Collision Test",
            nodes=[TRIGGER_NODE, existing_ascerta_node, copy.deepcopy(OPENAI_CHAT_MODEL_NODE)],
            connections={},
        )

        put_calls = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET" and path == "/api/v1/workflows":
                return {"data": [workflow]}
            if method == "GET" and path == "/api/v1/workflows/wf-1":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": [{"id": "c-1", "name": "Ascerta API", "type": "ascertaApi"}]}
            if method == "PUT":
                put_calls.append(body)
                return {}
            return {}

        env = {
            "N8N_BASE_URL": "http://localhost:5678",
            "N8N_API_KEY": "test-key",
            "ASCERTA_BASE_URL": "https://api.ascerta.com",
            "ASCERTA_API_KEY": "pk-test",
            "OPENAI_API_KEY": "sk-test",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("sys.argv", ["migrate", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(put_calls), 1)
        names = [n["name"] for n in put_calls[0]["nodes"]]
        self.assertIn("Ascerta Chat Model", names)       # existing
        self.assertIn("Ascerta Chat Model 1", names)     # new with suffix

    def test_multiple_openai_nodes_same_workflow(self):
        """Two OpenAI chat models in one workflow get distinct names."""
        node2 = copy.deepcopy(OPENAI_CHAT_MODEL_NODE)
        node2["id"] = "node-ddd"
        node2["name"] = "OpenAI Chat Model 1"
        node2["parameters"]["model"] = "gpt-4.1"

        workflow = make_workflow(
            "wf-1", "Multi-Node Test",
            nodes=[TRIGGER_NODE, copy.deepcopy(OPENAI_CHAT_MODEL_NODE), node2],
            connections={},
        )

        put_calls = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET" and path == "/api/v1/workflows":
                return {"data": [workflow]}
            if method == "GET" and path == "/api/v1/workflows/wf-1":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": [{"id": "c-1", "name": "Ascerta API", "type": "ascertaApi"}]}
            if method == "PUT":
                put_calls.append(body)
                return {}
            return {}

        env = {
            "N8N_BASE_URL": "http://localhost:5678",
            "N8N_API_KEY": "test-key",
            "ASCERTA_BASE_URL": "https://api.ascerta.com",
            "ASCERTA_API_KEY": "pk-test",
            "OPENAI_API_KEY": "sk-test",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("sys.argv", ["migrate", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(put_calls), 1)
        names = [n["name"] for n in put_calls[0]["nodes"]]
        # Both should be migrated with unique names
        ascerta_names = [n for n in names if n.startswith("Ascerta Chat Model")]
        self.assertEqual(len(ascerta_names), 2)
        self.assertEqual(len(set(ascerta_names)), 2)  # all unique


# ── Tests: prompt_select_nodes ────────────────────────────────────────────────

class TestPromptSelectNodes(unittest.TestCase):
    """Tests for the interactive node selection menu."""

    def _make_found(self):
        """Create a sample found-nodes list with mix of feasible and infeasible."""
        return [
            {
                "workflow_id": "wf-1", "workflow_name": "Bot A",
                "node": {"name": "OpenAI Chat Model"}, "node_type": "x",
                "provider": "openai", "replacement": "chat_model",
                "feasible": True, "label": "OpenAI Chat Model (LangChain)",
            },
            {
                "workflow_id": "wf-1", "workflow_name": "Bot A",
                "node": {"name": "Azure OpenAI Chat Model"}, "node_type": "x",
                "provider": "azureOpenai", "replacement": None,
                "feasible": False, "label": "Azure OpenAI Chat Model (LangChain)",
                "skip_reason": "Ascerta Chat Model currently supports OpenAI-compatible providers only",
            },
            {
                "workflow_id": "wf-2", "workflow_name": "Pipeline",
                "node": {"name": "OpenAI"}, "node_type": "x",
                "provider": "openai", "replacement": "proxy",
                "feasible": True, "label": "OpenAI (App Node)",
            },
        ]

    def test_all_selects_all_feasible(self):
        found = self._make_found()
        with patch("builtins.input", return_value="all"):
            selected = migrate.prompt_select_nodes(found)
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(n["feasible"] for n in selected))

    def test_empty_input_selects_all_feasible(self):
        found = self._make_found()
        with patch("builtins.input", return_value=""):
            selected = migrate.prompt_select_nodes(found)
        self.assertEqual(len(selected), 2)

    def test_none_selects_nothing(self):
        found = self._make_found()
        with patch("builtins.input", return_value="none"):
            selected = migrate.prompt_select_nodes(found)
        self.assertEqual(len(selected), 0)

    def test_specific_numbers(self):
        found = self._make_found()
        with patch("builtins.input", return_value="1,3"):
            selected = migrate.prompt_select_nodes(found)
        self.assertEqual(len(selected), 2)
        names = [n["node"]["name"] for n in selected]
        self.assertIn("OpenAI Chat Model", names)
        self.assertIn("OpenAI", names)

    def test_single_number(self):
        found = self._make_found()
        with patch("builtins.input", return_value="3"):
            selected = migrate.prompt_select_nodes(found)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["node"]["name"], "OpenAI")

    def test_infeasible_number_skipped(self):
        found = self._make_found()
        with patch("builtins.input", return_value="2"):
            selected = migrate.prompt_select_nodes(found)
        self.assertEqual(len(selected), 0)

    def test_out_of_range_skipped(self):
        found = self._make_found()
        with patch("builtins.input", return_value="99"):
            selected = migrate.prompt_select_nodes(found)
        self.assertEqual(len(selected), 0)

    def test_non_numeric_input_skipped(self):
        found = self._make_found()
        with patch("builtins.input", return_value="abc"):
            selected = migrate.prompt_select_nodes(found)
        self.assertEqual(len(selected), 0)

    def test_mixed_valid_and_invalid(self):
        found = self._make_found()
        with patch("builtins.input", return_value="1, 2, 99, abc"):
            selected = migrate.prompt_select_nodes(found)
        # Only #1 is valid and feasible; #2 is infeasible, #99 is out of range, abc is non-numeric
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["node"]["name"], "OpenAI Chat Model")

    def test_no_feasible_returns_empty(self):
        found = [
            {
                "workflow_id": "wf-1", "workflow_name": "Bot",
                "node": {"name": "Azure OpenAI"}, "node_type": "x",
                "provider": "azureOpenai", "replacement": None,
                "feasible": False, "label": "Azure OpenAI",
                "skip_reason": "not supported",
            },
        ]
        # Should not call input() when there are no migratable nodes
        selected = migrate.prompt_select_nodes(found)
        self.assertEqual(len(selected), 0)


# ── Tests: Sample Workflow Fixture ────────────────────────────────────────────

SAMPLE_WF_PATH = os.path.join(os.path.dirname(__file__), "sample-workflow-all-providers.json")


class TestSampleWorkflowFixture(unittest.TestCase):
    """Tests using the sample-workflow-all-providers.json fixture."""

    @classmethod
    def setUpClass(cls):
        with open(SAMPLE_WF_PATH) as f:
            cls.workflow = json.load(f)
        # Add id field like the API would return
        cls.workflow["id"] = "wf-sample"

    def test_detects_all_provider_nodes(self):
        found = migrate.find_llm_nodes([self.workflow])
        self.assertEqual(len(found), 5)  # 5 LLM nodes total

    def test_feasibility_classification(self):
        found = migrate.find_llm_nodes([self.workflow])
        feasible = [n for n in found if n["feasible"]]
        infeasible = [n for n in found if not n["feasible"]]
        # OpenAI Chat Model + OpenAI App Node + Anthropic Chat Model + Azure + Bedrock = 5 feasible
        self.assertEqual(len(feasible), 5)
        # All are now feasible
        self.assertEqual(len(infeasible), 0)

    def test_feasible_providers(self):
        found = migrate.find_llm_nodes([self.workflow])
        feasible = [n for n in found if n["feasible"]]
        providers = {n["provider"] for n in feasible}
        self.assertEqual(providers, {"openai", "anthropic", "azureOpenai", "bedrock"})

    def test_infeasible_providers(self):
        found = migrate.find_llm_nodes([self.workflow])
        infeasible = [n for n in found if not n["feasible"]]
        providers = {n["provider"] for n in infeasible}
        self.assertEqual(providers, set())

    def test_replacement_types(self):
        found = migrate.find_llm_nodes([self.workflow])
        feasible = sorted([n for n in found if n["feasible"]], key=lambda n: n["node"]["name"])
        # OpenAI App Node -> proxy
        app_node = next(n for n in feasible if n["node"]["name"] == "OpenAI")
        self.assertEqual(app_node["replacement"], "proxy")
        # OpenAI Chat Model -> chat_model
        chat_node = next(n for n in feasible if n["node"]["name"] == "OpenAI Chat Model")
        self.assertEqual(chat_node["replacement"], "chat_model")
        # Anthropic Chat Model -> chat_model_anthropic
        anthropic_node = next(n for n in feasible if n["node"]["name"] == "Anthropic Chat Model")
        self.assertEqual(anthropic_node["replacement"], "chat_model_anthropic")

    def test_chat_model_migration_preserves_model(self):
        """Build a Ascerta Chat Model from the sample's OpenAI Chat Model node."""
        found = migrate.find_llm_nodes([self.workflow])
        chat_info = next(n for n in found if n["node"]["name"] == "OpenAI Chat Model")
        result = migrate.build_ascerta_chat_model_node(
            chat_info["node"], ASCERTA_CRED, "sk-test", "Ascerta Chat Model"
        )
        self.assertEqual(result["parameters"]["model"], "gpt-4.1-mini")
        self.assertEqual(result["parameters"]["options"]["temperature"], 0.7)
        self.assertEqual(result["parameters"]["options"]["maxTokens"], 1024)
        self.assertEqual(result["parameters"]["options"]["topP"], 0.95)

    def test_proxy_migration_preserves_messages(self):
        """Build a Ascerta Proxy from the sample's OpenAI app node."""
        found = migrate.find_llm_nodes([self.workflow])
        app_info = next(n for n in found if n["node"]["name"] == "OpenAI")
        result = migrate.build_ascerta_proxy_node(
            app_info["node"], ASCERTA_CRED, "sk-test", "Ascerta Proxy"
        )
        msgs = json.loads(result["parameters"]["messages"])
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")

    def test_connection_rewiring_after_chat_model_rename(self):
        """Rewire connections when OpenAI Chat Model -> Ascerta Chat Model."""
        connections = copy.deepcopy(self.workflow["connections"])
        result = migrate.rewire_connections(connections, "OpenAI Chat Model", "Ascerta Chat Model")
        self.assertIn("Ascerta Chat Model", result)
        self.assertNotIn("OpenAI Chat Model", result)
        # Target should still point to AI Agent
        target = result["Ascerta Chat Model"]["ai_languageModel"][0][0]
        self.assertEqual(target["node"], "AI Agent")

    def test_connection_rewiring_after_proxy_rename(self):
        """Rewire connections when OpenAI -> Ascerta Proxy."""
        connections = copy.deepcopy(self.workflow["connections"])
        result = migrate.rewire_connections(connections, "OpenAI", "Ascerta Proxy")
        # "Manual Trigger" should now point to "Ascerta Proxy"
        trigger_target = result["Manual Trigger"]["main"][0][0]
        self.assertEqual(trigger_target["node"], "Ascerta Proxy")
        # Source key should be renamed
        self.assertIn("Ascerta Proxy", result)
        self.assertNotIn("OpenAI", result)

    def test_expression_references_in_agent_node(self):
        """Agent node has $('OpenAI Chat Model') and $('Anthropic Chat Model') references."""
        nodes = copy.deepcopy(self.workflow["nodes"])
        count = migrate.fix_expression_references(nodes, "OpenAI Chat Model", "Ascerta Chat Model")
        self.assertGreaterEqual(count, 1)
        agent = next(n for n in nodes if n["name"] == "AI Agent")
        self.assertIn("Ascerta Chat Model", agent["parameters"]["text"])
        # Anthropic ref should be untouched
        self.assertIn("Anthropic Chat Model", agent["parameters"]["fallback"])

    def test_full_dry_run_with_sample_workflow(self):
        """Full dry-run against the sample workflow fixture."""
        workflow = copy.deepcopy(self.workflow)
        env = {
            "N8N_BASE_URL": "http://localhost:5678",
            "N8N_API_KEY": "test-key",
            "ASCERTA_BASE_URL": "https://api.ascerta.com",
            "ASCERTA_API_KEY": "pk-test",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("sys.argv", ["migrate", "--dry-run", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request") as mock_req:
                    mock_req.side_effect = lambda method, path, body=None, quiet=False: {
                        ("/api/v1/workflows", "GET"): {"data": [workflow]},
                        ("/api/v1/workflows/wf-sample", "GET"): workflow,
                    }.get((path, method), {})
                    rc = migrate.main()
        self.assertEqual(rc, 0)

    def test_full_migration_with_sample_workflow(self):
        """Full migration of sample workflow — verifies all feasible node types replaced."""
        workflow = copy.deepcopy(self.workflow)
        put_calls = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET" and path == "/api/v1/workflows":
                return {"data": [workflow]}
            if method == "GET" and path == "/api/v1/workflows/wf-sample":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": [{"id": "c-1", "name": "Ascerta API", "type": "ascertaApi"}]}
            if method == "PUT":
                put_calls.append({"path": path, "body": body})
                return {}
            return {}

        env = {
            "N8N_BASE_URL": "http://localhost:5678",
            "N8N_API_KEY": "test-key",
            "ASCERTA_BASE_URL": "https://api.ascerta.com",
            "ASCERTA_API_KEY": "pk-test",
            "OPENAI_API_KEY": "sk-test",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "AZURE_OPENAI_API_KEY": "az-test",
            "AWS_ACCESS_KEY_ID": "AKIA-test",
            "AWS_SECRET_ACCESS_KEY": "secret-test",
            "AWS_REGION": "us-east-1",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("sys.argv", ["migrate", "--auto-yes", "--strategy", "replace"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(put_calls), 1)
        put_body = put_calls[0]["body"]
        node_types = {n["type"] for n in put_body["nodes"]}

        # All five Ascerta node types should be present
        self.assertIn("@ascerta/n8n-nodes-ascerta.lmChatAscerta", node_types)
        self.assertIn("@ascerta/n8n-nodes-ascerta.ascerta", node_types)
        self.assertIn("@ascerta/n8n-nodes-ascerta.lmChatAscertaAnthropic", node_types)
        self.assertIn("@ascerta/n8n-nodes-ascerta.lmChatAscertaAzure", node_types)
        self.assertIn("@ascerta/n8n-nodes-ascerta.lmChatAscertaBedrock", node_types)

        # All original native nodes should be gone
        self.assertNotIn("@n8n/n8n-nodes-langchain.lmChatOpenAi", node_types)
        self.assertNotIn("@n8n/n8n-nodes-langchain.openai", node_types)
        self.assertNotIn("@n8n/n8n-nodes-langchain.lmChatAnthropic", node_types)
        self.assertNotIn("@n8n/n8n-nodes-langchain.lmChatAzureOpenAi", node_types)
        self.assertNotIn("@n8n/n8n-nodes-langchain.lmChatAwsBedrock", node_types)

        # Connections should be rewired
        self.assertNotIn("OpenAI Chat Model", put_body["connections"])
        self.assertNotIn("OpenAI", put_body["connections"])
        self.assertIn("Ascerta Chat Model", put_body["connections"])
        self.assertIn("Ascerta Proxy", put_body["connections"])


# ── Tests: build_ascerta_chat_model_azure_node ──────────────────────────────────

AZURE_CHAT_MODEL_NODE = {
    "id": "azure-1",
    "name": "Azure OpenAI Chat Model",
    "type": "@n8n/n8n-nodes-langchain.lmChatAzureOpenAi",
    "typeVersion": 1,
    "position": [400, 200],
    "parameters": {
        "model": "gpt-4o",
        "apiVersion": "2024-06-01",
        "options": {"temperature": 0.5, "maxTokens": 2048},
    },
}


class TestBuildAscertaChatModelAzureNode(unittest.TestCase):
    def test_basic_fields(self):
        result = migrate.build_ascerta_chat_model_azure_node(
            AZURE_CHAT_MODEL_NODE, ASCERTA_CRED, "az-key-test", "Ascerta Azure OpenAI Chat Model"
        )
        self.assertEqual(result["type"], "@ascerta/n8n-nodes-ascerta.lmChatAscertaAzure")
        self.assertEqual(result["name"], "Ascerta Azure OpenAI Chat Model")
        self.assertEqual(result["parameters"]["deploymentName"], "gpt-4o")
        self.assertEqual(result["parameters"]["apiVersion"], "2024-06-01")
        self.assertNotIn("providerApiKey", result["parameters"])

    def test_options_preserved(self):
        result = migrate.build_ascerta_chat_model_azure_node(
            AZURE_CHAT_MODEL_NODE, ASCERTA_CRED, "az-key", "Test"
        )
        opts = result["parameters"]["options"]
        self.assertEqual(opts["temperature"], 0.5)
        self.assertEqual(opts["maxTokens"], 2048)

    def test_tracking_defaults(self):
        result = migrate.build_ascerta_chat_model_azure_node(
            AZURE_CHAT_MODEL_NODE, ASCERTA_CRED, "az-key", "Test"
        )
        self.assertEqual(result["parameters"]["useCaseName"], "={{ $workflow.name.replaceAll(' ', '-') }}")
        self.assertEqual(result["parameters"]["useCaseId"], "={{ 'azure/' + $parameter.deploymentName + '/' + $execution.id }}")
        self.assertEqual(result["parameters"]["useCaseStep"], "={{ $node.name }}")

    def test_no_plaintext_provider_key(self):
        """providerApiKey should NOT be in parameters — credentials are passed through."""
        result = migrate.build_ascerta_chat_model_azure_node(
            AZURE_CHAT_MODEL_NODE, ASCERTA_CRED, "az-dict-key", "Test"
        )
        self.assertNotIn("providerApiKey", result["parameters"])

    def test_resource_locator_model(self):
        node = copy.deepcopy(AZURE_CHAT_MODEL_NODE)
        node["parameters"]["model"] = {"mode": "list", "value": "gpt-4-turbo"}
        result = migrate.build_ascerta_chat_model_azure_node(node, ASCERTA_CRED, "k", "Test")
        self.assertEqual(result["parameters"]["deploymentName"], "gpt-4-turbo")

    def test_timeout_and_max_retries_preserved(self):
        """timeout and maxRetries should be extracted from native options."""
        node = copy.deepcopy(AZURE_CHAT_MODEL_NODE)
        node["parameters"]["options"]["timeout"] = 30000
        node["parameters"]["options"]["maxRetries"] = 3
        result = migrate.build_ascerta_chat_model_azure_node(node, ASCERTA_CRED, "k", "Test")
        opts = result["parameters"]["options"]
        self.assertEqual(opts["timeout"], 30000)
        self.assertEqual(opts["maxRetries"], 3)


# ── Tests: build_ascerta_chat_model_bedrock_node ────────────────────────────────

BEDROCK_CHAT_MODEL_NODE = {
    "id": "bedrock-1",
    "name": "AWS Bedrock Chat Model",
    "type": "@n8n/n8n-nodes-langchain.lmChatAwsBedrock",
    "typeVersion": 1,
    "position": [500, 200],
    "parameters": {
        "model": "anthropic.claude-3-sonnet-20240229-v1:0",
        "options": {"temperature": 0.7, "maxTokens": 4096},
    },
}


class TestBuildAscertaChatModelBedrockNode(unittest.TestCase):
    def test_basic_fields(self):
        result = migrate.build_ascerta_chat_model_bedrock_node(
            BEDROCK_CHAT_MODEL_NODE, ASCERTA_CRED, "", "Ascerta Bedrock Chat Model"
        )
        self.assertEqual(result["type"], "@ascerta/n8n-nodes-ascerta.lmChatAscertaBedrock")
        self.assertEqual(result["parameters"]["model"], "anthropic.claude-3-sonnet-20240229-v1:0")
        self.assertEqual(result["parameters"]["region"], "us-east-1")
        # No plaintext AWS credentials in parameters — they come from the aws credential
        self.assertNotIn("awsAccessKeyId", result["parameters"])
        self.assertNotIn("awsSecretAccessKey", result["parameters"])

    def test_options_preserved(self):
        result = migrate.build_ascerta_chat_model_bedrock_node(
            BEDROCK_CHAT_MODEL_NODE, ASCERTA_CRED, "", "Test"
        )
        self.assertEqual(result["parameters"]["options"]["temperature"], 0.7)
        self.assertEqual(result["parameters"]["options"]["maxTokens"], 4096)

    def test_native_aws_credential_passthrough(self):
        """AWS credential from original node should be passed through."""
        node = copy.deepcopy(BEDROCK_CHAT_MODEL_NODE)
        node["credentials"] = {"aws": {"id": "aws-cred-1", "name": "AWS account"}}
        result = migrate.build_ascerta_chat_model_bedrock_node(
            node, ASCERTA_CRED, "", "Test"
        )
        self.assertIn("aws", result["credentials"])
        self.assertEqual(result["credentials"]["aws"]["id"], "aws-cred-1")


# ── Tests: build_ascerta_proxy_anthropic_node ───────────────────────────────────

ANTHROPIC_APP_NODE = {
    "id": "anth-app-1",
    "name": "Anthropic",
    "type": "@n8n/n8n-nodes-langchain.anthropic",
    "typeVersion": 1,
    "position": [300, 400],
    "parameters": {
        "model": {"mode": "list", "value": "claude-sonnet-4-20250514"},
        "text": "Analyze this document for key themes.",
    },
}


class TestBuildAscertaProxyAnthropicNode(unittest.TestCase):
    def test_basic_fields(self):
        result = migrate.build_ascerta_proxy_anthropic_node(
            ANTHROPIC_APP_NODE, ASCERTA_CRED, "sk-ant-test", "Ascerta Proxy (Anthropic)"
        )
        self.assertEqual(result["type"], "@ascerta/n8n-nodes-ascerta.ascerta")
        self.assertEqual(result["parameters"]["provider"], "anthropic")
        self.assertEqual(result["parameters"]["model"], "claude-sonnet-4-20250514")
        # providerApiKey is still used in proxy nodes (they don't use dual credentials yet)
        self.assertEqual(result["parameters"]["providerApiKey"], "sk-ant-test")

    def test_messages_from_text(self):
        result = migrate.build_ascerta_proxy_anthropic_node(
            ANTHROPIC_APP_NODE, ASCERTA_CRED, "k", "Test"
        )
        import json
        messages = json.loads(result["parameters"]["messages"])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertIn("Analyze this document", messages[0]["content"])

    def test_tracking_defaults(self):
        result = migrate.build_ascerta_proxy_anthropic_node(
            ANTHROPIC_APP_NODE, ASCERTA_CRED, "k", "Test"
        )
        self.assertEqual(result["parameters"]["useCaseName"], "={{ $workflow.name.replaceAll(' ', '-') }}")
        self.assertEqual(result["parameters"]["useCaseId"], "={{ 'anthropic/' + $parameter.model + '/' + $execution.id }}")
        self.assertEqual(result["parameters"]["useCaseStep"], "={{ $node.name }}")


# ── Tests: credential redirect ───────────────────────────────────────────────

class TestCredentialRedirect(unittest.TestCase):
    def test_openai_redirect_patch(self):
        patch = migrate.build_credential_patch("openAiApi", "https://api.ascerta.com", "pk-test")
        self.assertEqual(patch["data"]["url"], "https://api.ascerta.com/api/v1/proxy/openai/v1")
        # All providers now include Ascerta key as custom header
        self.assertEqual(patch["data"]["headerName"], "xProxy-api-key")
        self.assertEqual(patch["data"]["headerValue"], "pk-test")

    def test_openai_redirect_merges_existing_data(self):
        existing = {"apiKey": "sk-existing-key", "url": "", "headerName": "", "headerValue": ""}
        patch = migrate.build_credential_patch("openAiApi", "https://api.ascerta.com", "pk-test",
                                               existing_data=existing)
        self.assertEqual(patch["data"]["url"], "https://api.ascerta.com/api/v1/proxy/openai/v1")
        self.assertEqual(patch["data"]["apiKey"], "sk-existing-key")
        self.assertEqual(patch["data"]["headerName"], "xProxy-api-key")
        self.assertEqual(patch["data"]["headerValue"], "pk-test")

    def test_anthropic_redirect_patch(self):
        patch = migrate.build_credential_patch("anthropicApi", "https://api.ascerta.com", "pk-test")
        self.assertEqual(patch["data"]["url"], "https://api.ascerta.com/api/v1/proxy/anthropic")
        self.assertEqual(patch["data"]["headerName"], "xProxy-api-key")
        self.assertEqual(patch["data"]["headerValue"], "pk-test")

    def test_anthropic_redirect_merges_existing_data(self):
        existing = {"apiKey": "sk-anth-key", "url": ""}
        patch = migrate.build_credential_patch("anthropicApi", "https://api.ascerta.com", "pk-test",
                                               existing_data=existing)
        self.assertEqual(patch["data"]["url"], "https://api.ascerta.com/api/v1/proxy/anthropic")
        self.assertEqual(patch["data"]["apiKey"], "sk-anth-key")
        self.assertEqual(patch["data"]["headerName"], "xProxy-api-key")

    def test_azure_redirect_patch(self):
        patch = migrate.build_credential_patch("azureOpenAiApi", "https://api.ascerta.com", "pk-test")
        self.assertEqual(patch["data"]["endpoint"], "https://api.ascerta.com/api/v1/proxy/azure.openai")
        self.assertEqual(patch["data"]["headerName"], "xProxy-api-key")
        self.assertEqual(patch["data"]["headerValue"], "pk-test")

    def test_azure_redirect_merges_existing_data(self):
        existing = {"apiKey": "az-key", "resourceName": "my-resource", "apiVersion": "2024-08-01-preview", "endpoint": ""}
        patch = migrate.build_credential_patch("azureOpenAiApi", "https://api.ascerta.com", "pk-test",
                                               existing_data=existing)
        self.assertEqual(patch["data"]["endpoint"], "https://api.ascerta.com/api/v1/proxy/azure.openai")
        self.assertEqual(patch["data"]["apiKey"], "az-key")
        self.assertEqual(patch["data"]["resourceName"], "my-resource")
        self.assertEqual(patch["data"]["apiVersion"], "2024-08-01-preview")

    def test_unsupported_type_returns_empty(self):
        patch = migrate.build_credential_patch("unknownApi", "https://api.ascerta.com", "pk-test")
        self.assertEqual(patch, {})

    def test_trailing_slash_stripped(self):
        patch = migrate.build_credential_patch("openAiApi", "https://api.ascerta.com/", "pk-test")
        self.assertEqual(patch["data"]["url"], "https://api.ascerta.com/api/v1/proxy/openai/v1")


# ── Tests: new node type detection ───────────────────────────────────────────

class TestNewNodeTypeDetection(unittest.TestCase):
    def test_detects_anthropic_app_node(self):
        nodes = [{"name": "Anth", "type": "@n8n/n8n-nodes-langchain.anthropic", "parameters": {}}]
        wf = make_workflow(nodes=nodes)
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["feasible"])
        self.assertEqual(found[0]["replacement"], "proxy_anthropic")

    def test_detects_openai_completion_model(self):
        nodes = [{"name": "GPT", "type": "@n8n/n8n-nodes-langchain.lmOpenAi", "parameters": {}}]
        wf = make_workflow(nodes=nodes)
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["feasible"])
        self.assertEqual(found[0]["replacement"], "chat_model")

    def test_detects_all_new_infeasible_types(self):
        new_types = [
            "@n8n/n8n-nodes-langchain.lmChatGroq",
            "@n8n/n8n-nodes-langchain.lmChatDeepSeek",
            "@n8n/n8n-nodes-langchain.lmChatCohere",
            "@n8n/n8n-nodes-langchain.lmChatXAiGrok",
            "@n8n/n8n-nodes-langchain.lmChatOpenRouter",
            "@n8n/n8n-nodes-langchain.lmChatOllama",
            "@n8n/n8n-nodes-langchain.lmChatVercelAiGateway",
            "@n8n/n8n-nodes-langchain.lmChatGoogleVertex",
            "@n8n/n8n-nodes-langchain.googleGemini",
            "@n8n/n8n-nodes-langchain.embeddingsOpenAi",
            "@n8n/n8n-nodes-langchain.embeddingsCohere",
            "@n8n/n8n-nodes-langchain.embeddingsOllama",
        ]
        nodes = [{"name": f"Node{i}", "type": t, "parameters": {}} for i, t in enumerate(new_types)]
        wf = make_workflow(nodes=nodes)
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), len(new_types))
        # All these are infeasible
        for n in found:
            self.assertFalse(n["feasible"], f"{n['label']} should be infeasible")

    def test_detects_embeddings_nodes(self):
        nodes = [
            {"name": "OAIEmbed", "type": "@n8n/n8n-nodes-langchain.embeddingsOpenAi", "parameters": {}},
            {"name": "AzureEmbed", "type": "@n8n/n8n-nodes-langchain.embeddingsAzureOpenAi", "parameters": {}},
            {"name": "BedrockEmbed", "type": "@n8n/n8n-nodes-langchain.embeddingsAwsBedrock", "parameters": {}},
        ]
        wf = make_workflow(nodes=nodes)
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 3)
        # All embeddings are currently infeasible
        for n in found:
            self.assertFalse(n["feasible"])


# ── Tests: Databricks ────────────────────────────────────────────────────────

DATABRICKS_NODE = {
    "id": "node-dbx",
    "name": "Databricks",
    "type": "n8n-nodes-databricks.databricks",
    "typeVersion": 1,
    "position": [500, 400],
    "parameters": {
        "endpoint": "my-llm-endpoint",
        "options": {
            "temperature": 0.8,
            "maxTokens": 4096,
            "topP": 0.95,
        },
    },
    "credentials": {
        "databricks": {"id": "dbx-cred-1", "name": "Databricks Workspace"},
    },
}

DATABRICKS_CHAT_MODEL_NODE = {
    "id": "node-dbx-chat",
    "name": "Databricks Chat Model",
    "type": "n8n-nodes-databricks.lmChatDatabricks",
    "typeVersion": 1,
    "position": [550, 400],
    "parameters": {
        "model": "databricks-gpt-5-4",
        "options": {
            "temperature": 0.7,
        },
    },
    "credentials": {
        "databricks": {"id": "dbx-cred-3", "name": "Databricks Chat"},
    },
}

DATABRICKS_AI_AGENT_NODE = {
    "id": "node-dbx-agent",
    "name": "Databricks AI Agent",
    "type": "n8n-nodes-databricks.databricksAiAgent",
    "typeVersion": 1,
    "position": [600, 400],
    "parameters": {
        "model": "databricks-meta-llama-3-3-70b-instruct",
        "options": {},
    },
    "credentials": {
        "databricks": {"id": "dbx-cred-2", "name": "Databricks Agent"},
    },
}


class TestDatabricksDetection(unittest.TestCase):
    def test_databricks_nodes_are_feasible(self):
        nodes = [
            {"name": "Databricks", "type": "n8n-nodes-databricks.databricks", "parameters": {}},
            {"name": "Databricks Chat Model", "type": "n8n-nodes-databricks.lmChatDatabricks", "parameters": {}},
            {"name": "Databricks Agent", "type": "n8n-nodes-databricks.databricksAiAgent", "parameters": {}},
        ]
        wf = make_workflow(nodes=nodes)
        found = migrate.find_llm_nodes([wf])
        self.assertEqual(len(found), 3)
        self.assertTrue(all(n["feasible"] for n in found))
        self.assertTrue(all(n["replacement"] == "chat_model_databricks" for n in found))


class TestBuildAscertaChatModelDatabricksCommunityNode(unittest.TestCase):
    def test_basic_fields(self):
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            DATABRICKS_NODE, ASCERTA_CRED, "dapi-test-token", "Ascerta Databricks Chat Model"
        )
        self.assertEqual(result["type"], "@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks")
        self.assertEqual(result["name"], "Ascerta Databricks Chat Model")
        self.assertEqual(result["id"], "node-dbx")
        self.assertEqual(result["position"], [500, 400])
        self.assertEqual(result["typeVersion"], 1)

    def test_endpoint_extracted(self):
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            DATABRICKS_NODE, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model"
        )
        self.assertEqual(result["parameters"]["endpointName"], {"mode": "name", "value": "my-llm-endpoint"})

    def test_endpoint_from_model_field(self):
        """When the community node uses 'model' instead of 'endpoint'."""
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            DATABRICKS_AI_AGENT_NODE, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model"
        )
        self.assertEqual(result["parameters"]["endpointName"], {"mode": "name", "value": "databricks-meta-llama-3-3-70b-instruct"})

    def test_options_preserved(self):
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            DATABRICKS_NODE, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model"
        )
        opts = result["parameters"]["options"]
        self.assertEqual(opts["temperature"], 0.8)
        self.assertEqual(opts["maxTokens"], 4096)
        self.assertEqual(opts["topP"], 0.95)

    def test_unsupported_options_excluded(self):
        node = copy.deepcopy(DATABRICKS_NODE)
        node["parameters"]["options"]["unknownOption"] = "bar"
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            node, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model"
        )
        self.assertNotIn("unknownOption", result["parameters"]["options"])

    def test_ascerta_databricks_credential(self):
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            DATABRICKS_NODE, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model",
            dbx_cred={"id": "ascerta-dbx-1", "name": "Ascerta Databricks API"},
        )
        self.assertNotIn("databricks", result["credentials"])
        self.assertEqual(result["credentials"]["ascertaDatabricksApi"]["id"], "ascerta-dbx-1")
        self.assertEqual(result["credentials"]["ascertaDatabricksApi"]["name"], "Ascerta Databricks API")

    def test_no_incompatible_native_databricks_credential(self):
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            DATABRICKS_NODE, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model"
        )
        self.assertNotIn("databricks", result["credentials"])
        self.assertNotIn("ascertaDatabricksApi", result["credentials"])

    def test_deployed_model_from_source(self):
        node = copy.deepcopy(DATABRICKS_NODE)
        node["parameters"]["deployedModel"] = {"mode": "name", "value": "my-model"}
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            node, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model"
        )
        self.assertEqual(result["parameters"]["deployedModel"], {"mode": "name", "value": "my-model"})

    def test_ascerta_credential_reference(self):
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            DATABRICKS_NODE, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model"
        )
        cred_ref = result["credentials"]["ascertaApi"]
        self.assertEqual(cred_ref["id"], "cred-123")
        self.assertEqual(cred_ref["name"], "Ascerta API")

    def test_no_plaintext_provider_key(self):
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            DATABRICKS_NODE, ASCERTA_CRED, "dapi-my-token", "Ascerta Databricks Chat Model"
        )
        self.assertNotIn("providerApiKey", result["parameters"])
        self.assertNotIn("accessToken", result["parameters"])

    def test_cloud_provider_defaults_to_aws(self):
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            DATABRICKS_NODE, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model"
        )
        self.assertEqual(result["parameters"]["cloudProvider"], "aws")

    def test_tracking_defaults(self):
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            DATABRICKS_NODE, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model"
        )
        params = result["parameters"]
        self.assertIn("useCaseName", params)
        self.assertIn("useCaseId", params)
        self.assertIn("useCaseStep", params)
        self.assertIn("databricks/", params["useCaseId"])

    def test_resource_locator_model(self):
        """Handle n8n 2.x resourceLocator format for endpoint field."""
        node = copy.deepcopy(DATABRICKS_NODE)
        node["parameters"]["endpoint"] = {"__rl": True, "value": "my-fancy-endpoint", "mode": "string"}
        result = migrate.build_ascerta_chat_model_databricks_community_node(
            node, ASCERTA_CRED, "dapi-test", "Ascerta Databricks Chat Model"
        )
        self.assertEqual(result["parameters"]["endpointName"], {"mode": "name", "value": "my-fancy-endpoint"})


# ── Tests: classify_databricks_shim ──────────────────────────────────────────

class TestClassifyDatabricksShim(unittest.TestCase):
    """Detection of lmChatOpenAi nodes pointed at Databricks workspaces."""

    def _node(self, base_url=None):
        params = {"model": "databricks-claude-sonnet-4-6"}
        if base_url is not None:
            params["options"] = {"baseURL": base_url}
        return {
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "parameters": params,
            "credentials": {"openAiApi": {"id": "cred-1", "name": "OpenAI"}},
        }

    def test_azure_databricks_hostname(self):
        node = self._node("https://abc.azuredatabricks.net/serving-endpoints/x/invocations")
        result = migrate.classify_databricks_shim(node, client=None)
        self.assertTrue(result["detected"])
        self.assertEqual(result["cloud_provider"], "azure")
        self.assertEqual(result["source"], "node_param")

    def test_aws_databricks_hostname(self):
        node = self._node("https://e2-demo.cloud.databricks.com/serving-endpoints/y/invocations")
        result = migrate.classify_databricks_shim(node, client=None)
        self.assertTrue(result["detected"])
        self.assertEqual(result["cloud_provider"], "aws")
        self.assertEqual(result["source"], "node_param")

    def test_plain_openai_url_is_not_a_shim(self):
        node = self._node("https://api.openai.com/v1")
        result = migrate.classify_databricks_shim(node, client=None)
        self.assertFalse(result["detected"])
        self.assertIsNone(result["cloud_provider"])

    def test_no_baseurl_and_no_client_is_not_a_shim(self):
        node = self._node(base_url=None)
        result = migrate.classify_databricks_shim(node, client=None)
        self.assertFalse(result["detected"])
        self.assertEqual(result["source"], "none")

    def test_baseurl_on_credential_when_node_has_none(self):
        node = self._node(base_url=None)
        client = MagicMock()
        with patch.object(migrate, "_fetch_credential_data",
                          return_value={"url": "https://corp.azuredatabricks.net/v1"}):
            result = migrate.classify_databricks_shim(node, client=client)
        self.assertTrue(result["detected"])
        self.assertEqual(result["cloud_provider"], "azure")
        self.assertEqual(result["source"], "credential")

    def test_malformed_baseurl_does_not_crash(self):
        node = self._node("not a url")
        result = migrate.classify_databricks_shim(node, client=None)
        self.assertFalse(result["detected"])

    def test_case_insensitive_hostname(self):
        node = self._node("https://ABC.AZUREDATABRICKS.NET/v1")
        result = migrate.classify_databricks_shim(node, client=None)
        self.assertTrue(result["detected"])
        self.assertEqual(result["cloud_provider"], "azure")

    def test_databricks_in_path_but_not_hostname_is_not_shim(self):
        node = self._node("https://api.openai.com/v1/databricks-shim")
        result = migrate.classify_databricks_shim(node, client=None)
        self.assertFalse(result["detected"])


# ── Tests: build_ascerta_chat_model_databricks_node (shim builder) ──────────────

DBX_SOURCE_NODE_STRING_MODEL = {
    "id": "src-1",
    "name": "OpenAI Chat Model",
    "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
    "typeVersion": 1,
    "position": [400, 300],
    "parameters": {
        "model": "databricks-claude-sonnet-4-6",
        "options": {
            "baseURL": "https://e2-demo.cloud.databricks.com/serving-endpoints/x/invocations",
            "temperature": 0.5,
            "maxTokens": 2048,
            "topP": 0.9,
        },
    },
    "credentials": {"openAiApi": {"id": "old-cred", "name": "OpenAI"}},
}

DBX_SOURCE_NODE_RL_MODEL = {
    "id": "src-2",
    "name": "OpenAI Chat Model RL",
    "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
    "typeVersion": 1,
    "position": [400, 300],
    "parameters": {
        "model": {"__rl": True, "mode": "list", "value": "gpt-4o"},
        "options": {"baseURL": "https://abc.azuredatabricks.net/v1"},
    },
}

DBX_CRED = {"id": "dbx-cred-1", "name": "Databricks PAT"}


class TestBuildAscertaChatModelDatabricksShimNode(unittest.TestCase):
    def test_builds_correct_type_and_position(self):
        result = migrate.build_ascerta_chat_model_databricks_node(
            DBX_SOURCE_NODE_STRING_MODEL, ASCERTA_CRED, DBX_CRED, "aws", "Ascerta Databricks Chat Model"
        )
        self.assertEqual(result["type"], "@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks")
        self.assertEqual(result["position"], [400, 300])
        self.assertEqual(result["name"], "Ascerta Databricks Chat Model")
        self.assertEqual(result["typeVersion"], 1)

    def test_endpoint_name_from_string_model(self):
        result = migrate.build_ascerta_chat_model_databricks_node(
            DBX_SOURCE_NODE_STRING_MODEL, ASCERTA_CRED, DBX_CRED, "aws", "X"
        )
        self.assertEqual(
            result["parameters"]["endpointName"],
            {"mode": "name", "value": "databricks-claude-sonnet-4-6"},
        )

    def test_endpoint_name_from_resourcelocator_model(self):
        result = migrate.build_ascerta_chat_model_databricks_node(
            DBX_SOURCE_NODE_RL_MODEL, ASCERTA_CRED, DBX_CRED, "azure", "X"
        )
        self.assertEqual(
            result["parameters"]["endpointName"],
            {"mode": "name", "value": "gpt-4o"},
        )
        self.assertEqual(result["parameters"]["cloudProvider"], "azure")

    def test_deployed_model_left_empty(self):
        result = migrate.build_ascerta_chat_model_databricks_node(
            DBX_SOURCE_NODE_STRING_MODEL, ASCERTA_CRED, DBX_CRED, "aws", "X"
        )
        self.assertEqual(result["parameters"]["deployedModel"], {"mode": "name", "value": ""})

    def test_options_subset_passed_through(self):
        result = migrate.build_ascerta_chat_model_databricks_node(
            DBX_SOURCE_NODE_STRING_MODEL, ASCERTA_CRED, DBX_CRED, "aws", "X"
        )
        opts = result["parameters"]["options"]
        self.assertEqual(opts["temperature"], 0.5)
        self.assertEqual(opts["maxTokens"], 2048)
        self.assertEqual(opts["topP"], 0.9)
        self.assertNotIn("baseURL", opts)  # baseURL is dropped — Ascerta node doesn't use it

    def test_credentials_with_dbx_cred(self):
        result = migrate.build_ascerta_chat_model_databricks_node(
            DBX_SOURCE_NODE_STRING_MODEL, ASCERTA_CRED, DBX_CRED, "aws", "X"
        )
        creds = result["credentials"]
        self.assertEqual(creds["ascertaApi"]["id"], "cred-123")
        self.assertEqual(creds["ascertaDatabricksApi"], {"id": "dbx-cred-1", "name": "Databricks PAT"})

    def test_credentials_without_dbx_cred(self):
        result = migrate.build_ascerta_chat_model_databricks_node(
            DBX_SOURCE_NODE_STRING_MODEL, ASCERTA_CRED, None, "aws", "X"
        )
        creds = result["credentials"]
        self.assertIn("ascertaApi", creds)
        self.assertNotIn("ascertaDatabricksApi", creds)

    def test_tracking_defaults(self):
        result = migrate.build_ascerta_chat_model_databricks_node(
            DBX_SOURCE_NODE_STRING_MODEL, ASCERTA_CRED, DBX_CRED, "aws", "X"
        )
        self.assertEqual(
            result["parameters"]["useCaseName"],
            "={{ $workflow.name.replaceAll(' ', '-') }}",
        )
        self.assertEqual(
            result["parameters"]["useCaseId"],
            "={{ 'databricks/' + $parameter.endpointName.value + '/' + $execution.id }}",
        )
        self.assertEqual(result["parameters"]["useCaseStep"], "={{ $node.name }}")


# ── Tests: Audit script Databricks awareness ─────────────────────────────────

DATABRICKS_WF_PATH = os.path.join(
    os.path.dirname(__file__), "test-workflow-ascerta-databricks.json"
)


class TestAuditDatabricksRecognition(unittest.TestCase):
    """The audit script must recognize the new lmChatAscertaDatabricks node and the
    ascertaDatabricksApi credential type so workflows already on the new Databricks
    proxy show up in audit reports instead of being silently dropped."""

    def test_databricks_node_in_ascerta_node_types(self):
        self.assertIn(
            "@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks", audit_ascerta.ASCERTA_NODE_TYPES
        )
        info = audit_ascerta.ASCERTA_NODE_TYPES["@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks"]
        self.assertEqual(info["category"], "ascerta_chat_model")
        self.assertEqual(info["label"], "Ascerta Databricks (Proxy)")

    def test_ascerta_node_labels_match_upstream(self):
        # Sanity-check: display labels match what @ascerta/n8n-nodes-ascerta v1.x ships.
        expected = {
            "@ascerta/n8n-nodes-ascerta.lmChatAscerta": "Ascerta OpenAI (Proxy)",
            "@ascerta/n8n-nodes-ascerta.lmChatAscertaAnthropic": "Ascerta Anthropic (Proxy)",
            "@ascerta/n8n-nodes-ascerta.lmChatAscertaAzure": "Ascerta Azure AI Foundry (Proxy)",
            "@ascerta/n8n-nodes-ascerta.lmChatAscertaBedrock": "Ascerta Amazon Bedrock (Proxy)",
            "@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks": "Ascerta Databricks (Proxy)",
        }
        for node_type, label in expected.items():
            self.assertEqual(audit_ascerta.ASCERTA_NODE_TYPES[node_type]["label"], label)

    def test_ascerta_databricks_credential_type_known(self):
        self.assertIn("ascertaDatabricksApi", audit_ascerta.KNOWN_ASCERTA_CREDENTIAL_TYPES)
        # Ascerta credentials are not redirect-eligible (they already point at Ascerta).
        self.assertNotIn(
            "ascertaDatabricksApi", audit_ascerta.SUPPORTED_CREDENTIAL_REDIRECT_TYPES
        )

    def test_audit_picks_up_databricks_workflow_fixture(self):
        with open(DATABRICKS_WF_PATH) as f:
            wf = json.load(f)
        report = audit_ascerta.build_analysis_report([wf])
        node_types = {n["node_type"] for n in report["nodes"]}
        self.assertIn("@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks", node_types)
        # The Databricks node should be classified as already-on-Ascerta.
        dbx = next(
            n for n in report["nodes"]
            if n["node_type"] == "@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks"
        )
        self.assertEqual(dbx["source"], "ascerta")
        self.assertEqual(dbx["recommended_action"], "already_on_ascerta")
        # Both Ascerta credentials should be tracked as used by the workflow.
        cred_keys = {c["credential_key"] for c in dbx["credential_refs"]}
        self.assertEqual(cred_keys, {"ascertaApi", "ascertaDatabricksApi"})

    def test_choose_migration_action_for_databricks_node(self):
        with open(DATABRICKS_WF_PATH) as f:
            wf = json.load(f)
        report = audit_ascerta.build_analysis_report([wf])
        dbx = next(
            n for n in report["nodes"]
            if n["node_type"] == "@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks"
        )
        decision = audit_ascerta.choose_migration_action(dbx, report)
        self.assertEqual(decision["path"], "already_on_ascerta")
        self.assertEqual(decision["confidence"], 1.0)


# ── Tests: resolve_ascerta_databricks_credential ────────────────────────────────

class TestResolveAscertaDatabricksCredential(unittest.TestCase):
    def _client_with_creds(self, creds):
        client = MagicMock()
        client.get = MagicMock(side_effect=lambda path, **kw: (
            {"data": creds} if path == "/api/v1/credentials"
            else next((c for c in creds if c.get("id") == path.rsplit("/", 1)[-1]), {})
        ))
        client.post = MagicMock(return_value={"id": "new-dbx", "name": "Databricks PAT"})
        return client

    def _args(self, **kw):
        ns = argparse.Namespace(
            databricks_credential_id=None,
            databricks_cloud="aws",
            auto_yes=False,
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

    def test_dry_run_returns_stub(self):
        client = self._client_with_creds([])
        result = migrate.resolve_ascerta_databricks_credential(
            client, self._args(), dry_run=True
        )
        self.assertEqual(result["id"], "dry-run-dbx")

    def test_one_existing_credential_reused(self):
        creds = [{"id": "abc", "name": "DBX 1", "type": "ascertaDatabricksApi"}]
        client = self._client_with_creds(creds)
        result = migrate.resolve_ascerta_databricks_credential(
            client, self._args(), dry_run=False
        )
        self.assertEqual(result["id"], "abc")
        self.assertEqual(result["name"], "DBX 1")

    def test_two_existing_creds_auto_yes_picks_first(self):
        creds = [
            {"id": "a", "name": "DBX A", "type": "ascertaDatabricksApi"},
            {"id": "b", "name": "DBX B", "type": "ascertaDatabricksApi"},
        ]
        client = self._client_with_creds(creds)
        result = migrate.resolve_ascerta_databricks_credential(
            client, self._args(auto_yes=True), dry_run=False
        )
        self.assertEqual(result["id"], "a")

    def test_explicit_id_resolved(self):
        creds = [{"id": "xyz", "name": "DBX Pinned", "type": "ascertaDatabricksApi"}]
        client = self._client_with_creds(creds)
        result = migrate.resolve_ascerta_databricks_credential(
            client, self._args(databricks_credential_id="xyz"), dry_run=False
        )
        self.assertEqual(result["id"], "xyz")

    def test_explicit_id_wrong_type_exits(self):
        creds = [{"id": "wrong", "name": "OAI", "type": "openAiApi"}]
        client = self._client_with_creds(creds)
        with self.assertRaises(SystemExit):
            migrate.resolve_ascerta_databricks_credential(
                client, self._args(databricks_credential_id="wrong"), dry_run=False
            )

    def test_two_creds_interactive_valid_pick(self):
        creds = [
            {"id": "a", "name": "DBX A", "type": "ascertaDatabricksApi"},
            {"id": "b", "name": "DBX B", "type": "ascertaDatabricksApi"},
        ]
        client = self._client_with_creds(creds)
        with patch("builtins.input", return_value="2"), \
             patch.object(migrate, "_is_interactive", return_value=True):
            result = migrate.resolve_ascerta_databricks_credential(
                client, self._args(), dry_run=False
            )
        self.assertEqual(result["id"], "b")

    def test_two_creds_interactive_zero_falls_back_to_first(self):
        """Regression: '0' previously returned the LAST credential (negative index)."""
        creds = [
            {"id": "a", "name": "DBX A", "type": "ascertaDatabricksApi"},
            {"id": "b", "name": "DBX B", "type": "ascertaDatabricksApi"},
        ]
        client = self._client_with_creds(creds)
        with patch("builtins.input", return_value="0"), \
             patch.object(migrate, "_is_interactive", return_value=True):
            result = migrate.resolve_ascerta_databricks_credential(
                client, self._args(), dry_run=False
            )
        self.assertEqual(result["id"], "a")  # first, not last

    def test_two_creds_interactive_out_of_range_falls_back_to_first(self):
        creds = [
            {"id": "a", "name": "DBX A", "type": "ascertaDatabricksApi"},
            {"id": "b", "name": "DBX B", "type": "ascertaDatabricksApi"},
        ]
        client = self._client_with_creds(creds)
        with patch("builtins.input", return_value="99"), \
             patch.object(migrate, "_is_interactive", return_value=True):
            result = migrate.resolve_ascerta_databricks_credential(
                client, self._args(), dry_run=False
            )
        self.assertEqual(result["id"], "a")

    def test_two_creds_interactive_invalid_string_falls_back_to_first(self):
        creds = [
            {"id": "a", "name": "DBX A", "type": "ascertaDatabricksApi"},
            {"id": "b", "name": "DBX B", "type": "ascertaDatabricksApi"},
        ]
        client = self._client_with_creds(creds)
        with patch("builtins.input", return_value="not a number"), \
             patch.object(migrate, "_is_interactive", return_value=True):
            result = migrate.resolve_ascerta_databricks_credential(
                client, self._args(), dry_run=False
            )
        self.assertEqual(result["id"], "a")

    def test_no_creds_with_env_vars_creates(self):
        client = self._client_with_creds([])
        env = {"ASCERTA_DBX_PAT": "dapi-test", "ASCERTA_DBX_WORKSPACE_URL": "https://x.cloud.databricks.com"}
        with patch.dict(os.environ, env, clear=False):
            result = migrate.resolve_ascerta_databricks_credential(
                client, self._args(auto_yes=True), dry_run=False
            )
        self.assertEqual(result["id"], "new-dbx")
        # POST was called with the PAT
        self.assertTrue(client.post.called)
        post_body = client.post.call_args[0][1]
        self.assertEqual(post_body["type"], "ascertaDatabricksApi")
        self.assertEqual(post_body["data"]["accessToken"], "dapi-test")
        self.assertEqual(post_body["data"]["workspaceUrl"], "https://x.cloud.databricks.com")

    def test_no_creds_no_env_no_interactive_returns_none(self):
        client = self._client_with_creds([])
        # Make sure the env vars are NOT set
        env_to_clear = {"ASCERTA_DBX_PAT": "", "ASCERTA_DBX_WORKSPACE_URL": ""}
        with patch.dict(os.environ, env_to_clear, clear=False):
            for var in ("ASCERTA_DBX_PAT", "ASCERTA_DBX_WORKSPACE_URL"):
                if var in os.environ and os.environ[var] == "":
                    del os.environ[var]
            result = migrate.resolve_ascerta_databricks_credential(
                client, self._args(auto_yes=True), dry_run=False
            )
        self.assertIsNone(result)


# ── Tests: Databricks shim end-to-end ────────────────────────────────────────

DBX_SHIM_WF_PATH = os.path.join(
    os.path.dirname(__file__), "test-workflow-databricks-shim.json"
)


class TestDatabricksShimEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DBX_SHIM_WF_PATH) as f:
            cls.workflow = json.load(f)

    def test_scan_classifies_shim_and_plain_separately(self):
        found = migrate.find_llm_nodes([self.workflow])
        self.assertEqual(len(found), 2)
        shim = next(n for n in found if n["node"]["name"] == "Databricks Shim")
        plain = next(n for n in found if n["node"]["name"] == "Plain OpenAI")
        self.assertEqual(shim["replacement"], "chat_model_databricks")
        self.assertEqual(plain["replacement"], "chat_model")

    def test_full_migration_produces_correct_node_types(self):
        workflow = copy.deepcopy(self.workflow)
        put_calls = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET" and path == "/api/v1/workflows":
                return {"data": [workflow]}
            if method == "GET" and path == "/api/v1/workflows/wf-dbx-shim":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": [
                    {"id": "c-ascerta", "name": "Ascerta API", "type": "ascertaApi"},
                    {"id": "c-dbx", "name": "Databricks PAT", "type": "ascertaDatabricksApi"},
                ]}
            if method == "PUT":
                put_calls.append({"path": path, "body": body})
                return {"nodes": (body or {}).get("nodes", [])}
            if method == "POST":
                return {"id": "new", "name": "?"}
            return {}

        env = {
            "N8N_BASE_URL": "http://localhost:5678",
            "N8N_API_KEY": "test-key",
            "ASCERTA_BASE_URL": "https://api.ascerta.com",
            "ASCERTA_API_KEY": "pk-test",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("sys.argv", ["migrate", "--auto-yes", "--strategy", "replace"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(put_calls), 1)
        node_types = {n["type"] for n in put_calls[0]["body"]["nodes"]}
        self.assertIn("@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks", node_types)
        self.assertIn("@ascerta/n8n-nodes-ascerta.lmChatAscerta", node_types)
        # Both native lmChatOpenAi nodes are gone
        self.assertNotIn("@n8n/n8n-nodes-langchain.lmChatOpenAi", node_types)

        # The Databricks node has the right cloudProvider
        dbx_node = next(n for n in put_calls[0]["body"]["nodes"]
                        if n["type"] == "@ascerta/n8n-nodes-ascerta.lmChatAscertaDatabricks")
        self.assertEqual(dbx_node["parameters"]["cloudProvider"], "aws")
        self.assertEqual(
            dbx_node["parameters"]["endpointName"]["value"],
            "databricks-claude-sonnet-4-6",
        )
        # ascertaDatabricksApi credential was wired up
        self.assertEqual(dbx_node["credentials"]["ascertaDatabricksApi"]["id"], "c-dbx")

    def test_dry_run_resolver_returns_stub_directly(self):
        """The dry-run path produces the sentinel stub credential
        without contacting n8n's credentials API."""
        client = MagicMock()
        client.get = MagicMock(side_effect=AssertionError(
            "dry-run should not call /api/v1/credentials"
        ))
        args = argparse.Namespace(
            databricks_credential_id=None,
            databricks_cloud="aws",
            auto_yes=True,
        )
        result = migrate.resolve_ascerta_databricks_credential(
            client, args, dry_run=True
        )
        self.assertEqual(result["id"], "dry-run-dbx")
        self.assertIn("dry run", result["name"].lower())

    def test_dry_run_full_flow_smoke(self):
        """Dry-run end-to-end on a workflow with a Databricks shim
        produces no PUT calls and exits 0."""
        workflow = copy.deepcopy(self.workflow)
        put_calls = []

        def mock_request(method, path, body=None, quiet=False):
            if method == "GET" and path == "/api/v1/workflows":
                return {"data": [workflow]}
            if method == "GET" and path == "/api/v1/workflows/wf-dbx-shim":
                return copy.deepcopy(workflow)
            if method == "GET" and path == "/api/v1/credentials":
                return {"data": []}
            if method == "PUT":
                put_calls.append({"path": path, "body": body})
                return {"nodes": (body or {}).get("nodes", [])}
            return {}

        env = {
            "N8N_BASE_URL": "http://localhost:5678",
            "N8N_API_KEY": "test-key",
            "ASCERTA_BASE_URL": "https://api.ascerta.com",
            "ASCERTA_API_KEY": "pk-test",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("sys.argv", ["migrate", "--dry-run", "--auto-yes"]):
                with patch.object(migrate.N8nApiClient, "_request", side_effect=mock_request):
                    rc = migrate.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(put_calls), 0)  # dry-run never PUTs


# ── Tests: audit-side classify_databricks_shim ───────────────────────────────

class TestAuditClassifyDatabricksShim(unittest.TestCase):
    def test_audit_classifies_shim(self):
        node = {
            "name": "DBX",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "parameters": {
                "model": "databricks-llama",
                "options": {"baseURL": "https://e2.cloud.databricks.com/v1"},
            },
        }
        result = audit_ascerta.classify_databricks_shim(node, client=None)
        self.assertTrue(result["detected"])
        self.assertEqual(result["cloud_provider"], "aws")

    def test_audit_report_has_databricks_shim_field(self):
        wf = {
            "id": "w1",
            "name": "Test",
            "nodes": [{
                "name": "DBX",
                "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
                "parameters": {
                    "model": "databricks-claude",
                    "options": {"baseURL": "https://x.azuredatabricks.net/v1"},
                },
            }],
            "connections": {},
        }
        report = audit_ascerta.build_analysis_report([wf])
        node = report["nodes"][0]
        self.assertIn("databricks_shim", node)
        self.assertTrue(node["databricks_shim"]["detected"])
        self.assertEqual(node["databricks_shim"]["cloud_provider"], "azure")
        self.assertEqual(node["recommended_action"], "replace_with_ascerta_databricks")

    def test_audit_does_not_classify_plain_openai_as_shim(self):
        """A plain lmChatOpenAi node gets databricks_shim with detected=False
        and keeps its original recommended_action."""
        wf = {
            "id": "w1",
            "name": "Test",
            "nodes": [{
                "name": "Plain",
                "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
                "parameters": {"model": "gpt-4o"},
            }],
            "connections": {},
        }
        report = audit_ascerta.build_analysis_report([wf])
        node = report["nodes"][0]
        self.assertIn("databricks_shim", node)
        self.assertFalse(node["databricks_shim"]["detected"])
        self.assertEqual(node["databricks_shim"]["source"], "none")
        # Original recommended_action is preserved (not overridden)
        self.assertNotEqual(node["recommended_action"], "replace_with_ascerta_databricks")


if __name__ == "__main__":
    unittest.main()
