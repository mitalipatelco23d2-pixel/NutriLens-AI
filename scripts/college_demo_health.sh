#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST="127.0.0.1"
PORT="8000"
BASE_URL="http://${HOST}:${PORT}"

echo "=========================================================="
echo "          NUTRILENS X COLLEGE DEMO HEALTH REPORT          "
echo "=========================================================="

API_STATUS="FAIL"
DB_STATUS="FAIL"
REDIS_STATUS="DEGRADED"
AUTH_DEMO_STATUS="FAIL"
SCAN_FAST_PATH_STATUS="FAIL"
OCR_FALLBACK_STATUS="BLOCKED_OWNER_AUTH"
ASK_NUTRI_STATUS="FAIL"

# 1. Check API Liveness
if curl -s -f "${BASE_URL}/health" >/dev/null 2>&1; then
    API_STATUS="PASS"
fi

# 2. Check Database / Services Readiness via /api/v1/health
HEALTH_JSON=$(curl -s "${BASE_URL}/api/v1/health" 2>/dev/null || echo "{}")
if echo "${HEALTH_JSON}" | grep -q '"postgres"[[:space:]]*:[[:space:]]*"healthy"'; then
    DB_STATUS="PASS"
elif echo "${HEALTH_JSON}" | grep -q '"postgres"[[:space:]]*:[[:space:]]*"unavailable"'; then
    DB_STATUS="FAIL"
fi

# 3. Check Redis if required
if echo "${HEALTH_JSON}" | grep -q '"redis"[[:space:]]*:[[:space:]]*"healthy"'; then
    REDIS_STATUS="PASS"
else
    # In local development mode, in-memory rate limiting is permitted; Redis is degraded/optional
    REDIS_STATUS="DEGRADED"
fi

# 4. Check Demo Auth Capabilities & Perform Real Demo Login
CAP_JSON=$(curl -s "${BASE_URL}/api/v1/auth/capabilities" 2>/dev/null || echo "{}")
TOKEN=""
if echo "${CAP_JSON}" | grep -q '"demo_login"[[:space:]]*:[[:space:]]*"READY"'; then
    LOGIN_RESP=$(curl -s -X POST "${BASE_URL}/api/v1/auth/demo/login" 2>/dev/null || echo "{}")
    TOKEN=$(echo "${LOGIN_RESP}" | sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
    if [ -n "${TOKEN}" ]; then
        AUTH_DEMO_STATUS="PASS"
    fi
fi

# 5. Check Ask Nutri with Real Governed Message
if [ -n "${TOKEN}" ]; then
    ASK_RESP=$(curl -s -X POST "${BASE_URL}/api/v1/assistant/messages" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{"message": "What is protein?"}' 2>/dev/null || echo "{}")
    if echo "${ASK_RESP}" | grep -q '"answer"'; then
        ASK_NUTRI_STATUS="PASS"
    fi
fi

# 6. Check Scan Fast Path / Capabilities
if [ -n "${TOKEN}" ]; then
    R3_CAPS=$(curl -s "${BASE_URL}/api/v1/r3/capabilities" -H "Authorization: Bearer ${TOKEN}" 2>/dev/null || echo "{}")
    if echo "${R3_CAPS}" | grep -q 'client-android-ocr'; then
        SCAN_FAST_PATH_STATUS="PASS"
    else
        SCAN_FAST_PATH_STATUS="DEGRADED"
    fi
fi

# 7. Check OCR Fallback (Server AI Worker)
MODELS_JSON=$(curl -s "${BASE_URL}/api/v1/models" 2>/dev/null || echo "{}")
if echo "${MODELS_JSON}" | grep -q '"server_ai_worker"'; then
    if echo "${MODELS_JSON}" | grep -q '"server_ai_worker"[^}]*"READY"'; then
        OCR_FALLBACK_STATUS="PASS"
    else
        OCR_FALLBACK_STATUS="BLOCKED_OWNER_AUTH"
    fi
fi

echo "COMPONENT               | STATUS"
echo "------------------------+---------------------------------"
printf "%-24s| %s\n" "API" "${API_STATUS}"
printf "%-24s| %s\n" "DATABASE" "${DB_STATUS}"
printf "%-24s| %s\n" "REDIS" "${REDIS_STATUS}"
printf "%-24s| %s\n" "AUTH_DEMO" "${AUTH_DEMO_STATUS}"
printf "%-24s| %s\n" "SCAN_FAST_PATH" "${SCAN_FAST_PATH_STATUS}"
printf "%-24s| %s\n" "OCR_FALLBACK" "${OCR_FALLBACK_STATUS}"
printf "%-24s| %s\n" "ASK_NUTRI" "${ASK_NUTRI_STATUS}"
echo "=========================================================="

if [ "${API_STATUS}" = "PASS" ] && [ "${DB_STATUS}" = "PASS" ] && [ "${AUTH_DEMO_STATUS}" = "PASS" ] && [ "${ASK_NUTRI_STATUS}" = "PASS" ]; then
    echo "Overall Demo Readiness: PASS"
    exit 0
else
    echo "Overall Demo Readiness: DEGRADED"
    exit 1
fi
