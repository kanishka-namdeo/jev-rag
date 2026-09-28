#!/bin/bash
# probe_public_gateway.sh — verify the user-provided DashScope endpoint serves
# all three models (qwen3.7-plus generator, qwen3.6-plus reasoning, kimi-k2.5 judge)
set -uo pipefail
BASE="https://coding-intl.dashscope.aliyuncs.com/v1"
KEY="REDACTED-DASHSCOPE-KEY"

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
    print('PARSE FAIL:', str(e)[:200]); print(sys.stdin.read()[:300] if False else '')
"
  echo
done

echo "=== judge smoke: kimi-k2.5 with response_format json_object ==="
curl -s -m 60 "$BASE/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "kimi-k2.5", "messages": [{"role": "user", "content": "Return a JSON object {\"verdict\": \"support\", \"confidence\": 0.9} judging this claim: the sky is blue."}], "max_tokens": 100, "temperature": 0, "response_format": {"type": "json_object"}}' | head -c 600
echo
