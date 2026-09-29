#!/usr/bin/env bash
#
# migrate-openai-to-ascerta.sh
#
# Redirects existing n8n OpenAI credentials to route through Ascerta proxy.
# Uses the n8n REST API — works on both self-hosted and cloud instances.
#
# Usage:
#   ./migrate-openai-to-ascerta.sh
#
# Required environment variables:
#   N8N_BASE_URL    - Your n8n instance URL (e.g. http://localhost:5678 or https://yourname.app.n8n.cloud)
#   N8N_API_KEY     - Your n8n API key (Settings > API > Create API Key)
#   ASCERTA_BASE_URL   - Your Ascerta instance URL (e.g. https://api.yourcompany.ascerta.com)
#   ASCERTA_API_KEY    - Your Ascerta API key (optional — prints reminder if not set)
#
# What it does:
#   1. Lists all credentials in your n8n instance
#   2. Finds OpenAI credentials (type: openAiApi)
#   3. Shows current base URL for each
#   4. Asks for confirmation before updating
#   5. Updates the base URL to: {ASCERTA_BASE_URL}/api/v1/proxy/openai/v1
#
# To revert:
#   Set ASCERTA_BASE_URL=https://api.openai.com and re-run the script,
#   or manually edit each credential in the n8n UI.
#

set -euo pipefail

# ── Check required env vars ──────────────────────────────────────────────────

if [[ -z "${N8N_BASE_URL:-}" ]]; then
  echo "ERROR: N8N_BASE_URL is not set"
  echo "  export N8N_BASE_URL=http://localhost:5678"
  exit 1
fi

if [[ -z "${N8N_API_KEY:-}" ]]; then
  echo "ERROR: N8N_API_KEY is not set"
  echo "  Go to n8n Settings > API > Create an API Key"
  echo "  export N8N_API_KEY=your-api-key"
  exit 1
fi

if [[ -z "${ASCERTA_BASE_URL:-}" ]]; then
  echo "ERROR: ASCERTA_BASE_URL is not set"
  echo "  export ASCERTA_BASE_URL=https://api.yourcompany.ascerta.com"
  exit 1
fi

# Enforce HTTPS on Ascerta URL
if [[ ! "${ASCERTA_BASE_URL}" =~ ^https:// ]]; then
  echo "ERROR: ASCERTA_BASE_URL must start with https://"
  exit 1
fi

# Strip trailing slash
ASCERTA_BASE_URL="${ASCERTA_BASE_URL%/}"
N8N_BASE_URL="${N8N_BASE_URL%/}"

PROXY_URL="${ASCERTA_BASE_URL}/api/v1/proxy/openai/v1"

echo "══════════════════════════════════════════════════════════"
echo "  Ascerta Migration Script for n8n OpenAI Credentials"
echo "══════════════════════════════════════════════════════════"
echo ""
echo "  n8n instance:    ${N8N_BASE_URL}"
echo "  Ascerta proxy URL: ${PROXY_URL}"
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

# ── Find OpenAI credentials ─────────────────────────────────────────────────

# Extract OpenAI credentials (type = openAiApi)
OPENAI_CREDS=$(echo "$CREDS_BODY" | python3 -c "
import json, sys
data = json.load(sys.stdin)
creds = data.get('data', data) if isinstance(data, dict) else data
found = [c for c in creds if c.get('type') == 'openAiApi']
print(json.dumps(found))
" 2>/dev/null || echo "[]")

CRED_COUNT=$(echo "$OPENAI_CREDS" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")

if [[ "$CRED_COUNT" == "0" ]]; then
  echo "No OpenAI credentials found in this n8n instance."
  echo ""
  echo "This script only migrates built-in OpenAI credentials."
  echo "For Anthropic, Azure OpenAI, and AWS Bedrock, use the Ascerta Proxy node."
  exit 0
fi

echo "Found ${CRED_COUNT} OpenAI credential(s):"
echo ""

# List them
echo "$OPENAI_CREDS" | python3 -c "
import json, sys
creds = json.load(sys.stdin)
for c in creds:
    print(f\"  [{c['id']}] {c['name']} (type: {c['type']})\")
"
echo ""

# ── Confirm ──────────────────────────────────────────────────────────────────

echo "This will update the base URL on all ${CRED_COUNT} OpenAI credential(s) to:"
echo "  ${PROXY_URL}"
echo ""
read -r -p "Proceed? (y/N) " CONFIRM
if [[ "${CONFIRM}" != "y" && "${CONFIRM}" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

echo ""

# ── Update each credential ───────────────────────────────────────────────────

echo "$OPENAI_CREDS" | python3 -c "
import json, sys
creds = json.load(sys.stdin)
for c in creds:
    print(f\"{c['id']}|{c['name']}\")
" | while IFS='|' read -r CRED_ID CRED_NAME; do

  echo "Updating credential [${CRED_ID}] ${CRED_NAME}..."

  # Update via PATCH with new URL
  UPDATE_RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X PATCH \
    -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"data\":{\"url\":\"${PROXY_URL}\"}}" \
    "${N8N_BASE_URL}/api/v1/credentials/${CRED_ID}")

  UPDATE_CODE=$(echo "$UPDATE_RESPONSE" | tail -1)

  if [[ "$UPDATE_CODE" == "200" ]]; then
    echo "  ✓ Updated successfully"
  else
    UPDATE_BODY=$(echo "$UPDATE_RESPONSE" | sed '$d')
    echo "  ✗ Failed (HTTP ${UPDATE_CODE})"
    echo "    ${UPDATE_BODY}"
    echo ""
    echo "  You can update this credential manually in the n8n UI:"
    echo "  Settings > Credentials > ${CRED_NAME} > Base URL > ${PROXY_URL}"
  fi
done

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Migration complete!"
echo "══════════════════════════════════════════════════════════"
echo ""
echo "All OpenAI API calls will now route through Ascerta at:"
echo "  ${PROXY_URL}"
echo ""
if [[ -z "${ASCERTA_API_KEY:-}" ]]; then
  echo "REMINDER: Make sure each workflow also sends the xProxy-api-key header."
  echo "The Ascerta Proxy node handles this automatically, but for built-in"
  echo "OpenAI nodes you may need to add it via n8n's HTTP header options."
  echo ""
fi
echo "To revert, edit each credential in the n8n UI and change the"
echo "base URL back to: https://api.openai.com/v1"
echo ""
echo "For Anthropic, Azure OpenAI, and AWS Bedrock providers,"
echo "use the Ascerta Proxy node (@ascerta/n8n-nodes-ascerta) instead."
