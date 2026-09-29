#!/usr/bin/env bash
#
# migrate-to-ascerta.sh
#
# Redirects existing n8n LLM credentials to route through Ascerta proxy.
# Uses the n8n REST API — works on both self-hosted and cloud instances.
#
# Supported credential types:
#   - OpenAI (openAiApi)         → base URL redirect
#   - Anthropic (anthropicApi)   → base URL redirect + xProxy-api-key header
#   - Azure OpenAI (azureOpenAiApi) → endpoint redirect
#
# IMPORTANT: n8n's credential PATCH API replaces the entire data object,
# so provider API keys must be supplied. The script will prompt for each
# credential's API key during migration.
#
# Usage:
#   export N8N_BASE_URL=http://localhost:5678
#   export N8N_API_KEY=your-n8n-api-key
#   export ASCERTA_BASE_URL=https://api.yourcompany.ascerta.com
#   export ASCERTA_API_KEY=your-ascerta-api-key
#   ./migrate-to-ascerta.sh
#
# To revert, re-run with original provider URLs or edit credentials in the n8n UI.
#

set -euo pipefail

# ── Check required env vars ──────────────────────────────────────────────────

for VAR in N8N_BASE_URL N8N_API_KEY ASCERTA_BASE_URL ASCERTA_API_KEY; do
  if [[ -z "${!VAR:-}" ]]; then
    echo "ERROR: ${VAR} is not set"
    echo ""
    echo "Required environment variables:"
    echo "  N8N_BASE_URL   - Your n8n instance (e.g. http://localhost:5678)"
    echo "  N8N_API_KEY    - n8n API key (Settings > API > Create API Key)"
    echo "  ASCERTA_BASE_URL  - Ascerta instance (e.g. https://api.yourcompany.ascerta.com)"
    echo "  ASCERTA_API_KEY   - Your Ascerta API key"
    exit 1
  fi
done

if [[ ! "${ASCERTA_BASE_URL}" =~ ^https:// ]]; then
  echo "ERROR: ASCERTA_BASE_URL must start with https://"
  exit 1
fi

ASCERTA_BASE_URL="${ASCERTA_BASE_URL%/}"
N8N_BASE_URL="${N8N_BASE_URL%/}"

echo "══════════════════════════════════════════════════════════════"
echo "  Ascerta Migration Script for n8n LLM Credentials"
echo "══════════════════════════════════════════════════════════════"
echo ""
echo "  n8n instance:  ${N8N_BASE_URL}"
echo "  Ascerta base:    ${ASCERTA_BASE_URL}"
echo ""
echo "  Provider proxy URLs:"
echo "    OpenAI:       ${ASCERTA_BASE_URL}/api/v1/proxy/openai/v1"
echo "    Anthropic:    ${ASCERTA_BASE_URL}/api/v1/proxy/anthropic"
echo "    Azure OpenAI: ${ASCERTA_BASE_URL}/api/v1/proxy/azure.openai"
echo ""
echo "  NOTE: n8n requires the full credential data on update."
echo "  You will be prompted for each credential's provider API key."
echo ""

# ── Fetch all credentials ────────────────────────────────────────────────────

echo "Fetching credentials from n8n..."
CREDS_RESPONSE=$(curl -s -w "\n%{http_code}" \
  -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
  "${N8N_BASE_URL}/api/v1/credentials")

HTTP_CODE=$(echo "$CREDS_RESPONSE" | tail -1)
CREDS_BODY=$(echo "$CREDS_RESPONSE" | sed '$d')

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "ERROR: Failed to fetch credentials (HTTP ${HTTP_CODE})"
  echo "$CREDS_BODY"
  exit 1
fi

# ── Find matching credentials ────────────────────────────────────────────────

RESULTS=$(echo "$CREDS_BODY" | python3 -c "
import json, sys
data = json.load(sys.stdin)
creds = data.get('data', data) if isinstance(data, dict) else data
supported = {'openAiApi', 'anthropicApi', 'azureOpenAiApi'}
found = [c for c in creds if c.get('type') in supported]
print(json.dumps(found))
" 2>/dev/null || echo "[]")

TOTAL=$(echo "$RESULTS" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")

if [[ "$TOTAL" == "0" ]]; then
  echo "No OpenAI, Anthropic, or Azure OpenAI credentials found."
  echo ""
  echo "For AWS Bedrock, use the Ascerta Proxy node (@ascerta/n8n-nodes-ascerta) instead."
  exit 0
fi

echo "Found ${TOTAL} credential(s) to migrate:"
echo ""

echo "$RESULTS" | python3 -c "
import json, sys
creds = json.load(sys.stdin)
labels = {'openAiApi': 'OpenAI', 'anthropicApi': 'Anthropic', 'azureOpenAiApi': 'Azure OpenAI'}
for c in creds:
    label = labels.get(c['type'], c['type'])
    print(f\"  [{c['id']}] {c['name']} ({label})\")
"

echo ""
read -r -p "Proceed with migration? (y/N) " CONFIRM
if [[ "${CONFIRM}" != "y" && "${CONFIRM}" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi
echo ""

# ── Update credentials ───────────────────────────────────────────────────────

UPDATED=0
FAILED=0
SKIPPED=0

echo "$RESULTS" | python3 -c "
import json, sys
creds = json.load(sys.stdin)
for c in creds:
    print(f\"{c['id']}|{c['type']}|{c['name']}\")
" | while IFS='|' read -r CRED_ID CRED_TYPE CRED_NAME; do

  case "${CRED_TYPE}" in
    openAiApi)
      PROXY_URL="${ASCERTA_BASE_URL}/api/v1/proxy/openai/v1"
      LABEL="OpenAI"

      echo "─── [${CRED_ID}] ${CRED_NAME} (${LABEL}) ───"
      echo "  New base URL: ${PROXY_URL}"
      echo ""
      read -r -p "  Enter the OpenAI API key for '${CRED_NAME}' (or 's' to skip): " PROVIDER_KEY
      if [[ "${PROVIDER_KEY}" == "s" || -z "${PROVIDER_KEY}" ]]; then
        echo "  Skipped."
        echo ""
        SKIPPED=$((SKIPPED + 1))
        continue
      fi

      # Build JSON with python to handle special characters safely
      PATCH_DATA=$(python3 -c "
import json
print(json.dumps({'data': {
    'apiKey': '''${PROVIDER_KEY}''',
    'url': '${PROXY_URL}',
    'headerName': '',
    'headerValue': ''
}}))
" 2>/dev/null)
      ;;

    anthropicApi)
      PROXY_URL="${ASCERTA_BASE_URL}/api/v1/proxy/anthropic"
      LABEL="Anthropic"

      echo "─── [${CRED_ID}] ${CRED_NAME} (${LABEL}) ───"
      echo "  New base URL: ${PROXY_URL}"
      echo "  Will set xProxy-api-key header automatically."
      echo ""
      read -r -p "  Enter the Anthropic API key for '${CRED_NAME}' (or 's' to skip): " PROVIDER_KEY
      if [[ "${PROVIDER_KEY}" == "s" || -z "${PROVIDER_KEY}" ]]; then
        echo "  Skipped."
        echo ""
        SKIPPED=$((SKIPPED + 1))
        continue
      fi

      PATCH_DATA=$(python3 -c "
import json
print(json.dumps({'data': {
    'apiKey': '''${PROVIDER_KEY}''',
    'url': '${PROXY_URL}',
    'headerName': 'xProxy-api-key',
    'headerValue': '${ASCERTA_API_KEY}'
}}))
" 2>/dev/null)
      ;;

    azureOpenAiApi)
      PROXY_URL="${ASCERTA_BASE_URL}/api/v1/proxy/azure.openai"
      LABEL="Azure OpenAI"

      echo "─── [${CRED_ID}] ${CRED_NAME} (${LABEL}) ───"
      echo "  New endpoint: ${PROXY_URL}"
      echo ""
      read -r -p "  Enter the Azure OpenAI API key for '${CRED_NAME}' (or 's' to skip): " PROVIDER_KEY
      if [[ "${PROVIDER_KEY}" == "s" || -z "${PROVIDER_KEY}" ]]; then
        echo "  Skipped."
        echo ""
        SKIPPED=$((SKIPPED + 1))
        continue
      fi

      PATCH_DATA=$(python3 -c "
import json
print(json.dumps({'data': {
    'apiKey': '''${PROVIDER_KEY}''',
    'endpoint': '${PROXY_URL}',
    'headerName': '',
    'headerValue': ''
}}))
" 2>/dev/null)
      ;;

    *)
      echo "  Skipping [${CRED_ID}] ${CRED_NAME} (unsupported type: ${CRED_TYPE})"
      SKIPPED=$((SKIPPED + 1))
      continue
      ;;
  esac

  echo "  Updating..."

  UPDATE_RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X PATCH \
    -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "${PATCH_DATA}" \
    "${N8N_BASE_URL}/api/v1/credentials/${CRED_ID}")

  UPDATE_CODE=$(echo "$UPDATE_RESPONSE" | tail -1)

  if [[ "$UPDATE_CODE" == "200" ]]; then
    echo "  ✓ Updated successfully"
    UPDATED=$((UPDATED + 1))
  else
    UPDATE_BODY=$(echo "$UPDATE_RESPONSE" | sed '$d')
    echo "  ✗ Failed (HTTP ${UPDATE_CODE})"
    echo "    ${UPDATE_BODY}"
    echo ""
    echo "  Manual fix: n8n UI > Credentials > ${CRED_NAME} > Base URL > ${PROXY_URL}"
    FAILED=$((FAILED + 1))
  fi
  echo ""
done

echo "══════════════════════════════════════════════════════════════"
echo "  Migration complete!"
echo "══════════════════════════════════════════════════════════════"
echo ""
echo "Notes:"
echo "  - Anthropic credentials include the xProxy-api-key header automatically."
echo ""
echo "  - OpenAI and Azure OpenAI credentials do NOT have a custom header field."
echo "    For these providers, the Ascerta API key must be injected at the"
echo "    network/infrastructure level, or use the Ascerta Proxy node instead."
echo ""
echo "To revert:"
echo "  OpenAI:       Set base URL back to https://api.openai.com/v1"
echo "  Anthropic:    Set base URL back to https://api.anthropic.com"
echo "                and remove the xProxy-api-key header"
echo "  Azure OpenAI: Set endpoint back to your original Azure endpoint"
echo ""
echo "For AWS Bedrock, use the Ascerta Proxy node — n8n's Bedrock"
echo "credentials do not support base URL overrides."
