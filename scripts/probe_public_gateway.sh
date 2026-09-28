#!/bin/bash
# probe_public_gateway.sh — verify the configured OpenAI-compatible endpoint serves
# all three models (qwen3.7-plus generator, qwen3.6-plus reasoning, kimi-k2.5 judge).
#
# Endpoint + key come from JEVRAG_DASHSCOPE_BASE_URL / JEVRAG_DASHSCOPE_API_KEY
# (environment, or backend/.env — keys are never hardcoded; see docs/setup.md).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ENV_FILE="$ROOT/backend/.env"
if [ -f "$ENV_FILE" ]; then
  [ -z "${JEVRAG_DASHSCOPE_API_KEY:-}" ] && \
    JEVRAG_DASHSCOPE_API_KEY="$(sed -n 's/^JEVRAG_DASHSCOPE_API_KEY=//p' "$ENV_FILE" | head -1)"
  [ -z "${JEVRAG_DASHSCOPE_BASE_URL:-}" ] && \
    JEVRAG_DASHSCOPE_BASE_URL="$(sed -n 's/^JEVRAG_DASHSCOPE_BASE_URL=//p' "$ENV_FILE" | head -1)"
fi

BASE="${JEVRAG_DASHSCOPE_BASE_URL:-https://coding-intl.dashscope.aliyuncs.com/v1}"
KEY="${JEVRAG_DASHSCOPE_API_KEY:-}"
if [ -z "$KEY" ]; then
  echo "FATAL: JEVRAG_DASHSCOPE_API_KEY not set (env var or backend/.env)" >&2
  exit 1
fi
echo "probing endpoint: $BASE"

echo "=== GET /models ==="
curl -s -m 30 "$BASE/models" -H "Authorization: Bearer $KEY" | head -c 2000
echo; echo

for M in qwen3.7-plus qwen3.6-plus kimi-k2.5; do
  echo "=== chat: $M ==="
  RESP=$(curl -s -m 60 "$BASE/chat/completions" \
    -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
    -d "{\"model\": \"$M\", \"messages\": [{\"role\": \"user\", \"content\": \"Reply with exactly: OK-$M\"}], \"max_tokens\": 20, \"temperature\": 0}")
  echo "$RESP" | python3 -c "
import json,sys
try:
    r = json.load(sys.stdin)
    if 'choices' in r:
        print('REPLY:', r['choices'][0]['message']['content'][:80])
        print('usage:', r.get('usage', {}).get('total_tokens', 'n/a'))
    else:
        print('ERROR:', json.dumps(r)[:300])
except Exception as e:
    print('PARSE FAIL:', str(e)[:200])
"
  echo
done

echo "=== judge smoke: kimi-k2.5 with response_format json_object ==="
curl -s -m 60 "$BASE/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "kimi-k2.5", "messages": [{"role": "user", "content": "Return a JSON object {\"verdict\": \"support\", \"confidence\": 0.9} judging this claim: the sky is blue."}], "max_tokens": 100, "temperature": 0, "response_format": {"type": "json_object"}}' | head -c 600
echo
