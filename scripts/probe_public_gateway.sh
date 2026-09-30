#!/bin/bash
# probe_public_gateway.sh — verify the configured OpenAI-compatible endpoint serves
# all three models (qwen3.7-plus generator, qwen3.6-plus reasoning, kimi-k2.5 judge)
# AND that the judge accepts response_format json_object.
#
# Endpoint + key come from JEVRAG_DASHSCOPE_BASE_URL / JEVRAG_DASHSCOPE_API_KEY
# (environment, or backend/.env — keys are never hardcoded; see docs/setup.md).
# Values read out of backend/.env are CR-stripped: a CRLF .env (normal on a Windows
# checkout) otherwise lands a \r inside the Authorization header and the URL, which
# makes every curl fail and used to print "PARSE FAIL" for all three models while
# still exiting 0. This probe must be able to say NO: exit 1 on any failure.
#
# Exit codes: 0 all three models + the judge json_object smoke answered
#             1 a model call failed, or the endpoint/key is unusable
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAILURES=0

fail() { echo "FAIL: $1" >&2; FAILURES=$((FAILURES + 1)); }

ENV_FILE="$ROOT/backend/.env"
if [ -f "$ENV_FILE" ]; then
  [ -z "${JEVRAG_DASHSCOPE_API_KEY:-}" ] && \
    JEVRAG_DASHSCOPE_API_KEY="$(sed -n 's/^JEVRAG_DASHSCOPE_API_KEY=//p' "$ENV_FILE" | head -1 | tr -d '\r\n')"
  [ -z "${JEVRAG_DASHSCOPE_BASE_URL:-}" ] && \
    JEVRAG_DASHSCOPE_BASE_URL="$(sed -n 's/^JEVRAG_DASHSCOPE_BASE_URL=//p' "$ENV_FILE" | head -1 | tr -d '\r\n')"
fi

BASE="${JEVRAG_DASHSCOPE_BASE_URL:-https://coding-intl.dashscope.aliyuncs.com/v1}"
KEY="${JEVRAG_DASHSCOPE_API_KEY:-}"
if [ -z "$KEY" ]; then
  echo "FATAL: JEVRAG_DASHSCOPE_API_KEY not set (env var or backend/.env)" >&2
  exit 1
fi
BASE="${BASE%/}"
echo "probing endpoint: $BASE"

BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT

# chat <model> <json-payload> — prints the reply, records a failure on any error.
chat() {
  local model="$1" payload="$2" http
  http="$(curl -sS -m 90 -o "$BODY" -w '%{http_code}' \
    "$BASE/chat/completions" \
    -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    -d "$payload" 2>/dev/null)"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    fail "$model: curl exited $rc (network/TLS/DNS)"
    return 1
  fi
  if [ "$http" != "200" ]; then
    fail "$model: HTTP $http — $(head -c 200 "$BODY")"
    return 1
  fi
  python3 - "$model" "$BODY" <<'PY' || FAILURES=$((FAILURES + 1))
import json, sys
model, body = sys.argv[1], sys.argv[2]
try:
    r = json.load(open(body, encoding="utf-8"))
except Exception as exc:
    print("FAIL: %s: unparseable response (%s): %s"
          % (model, exc, open(body, encoding="utf-8", errors="replace").read()[:200]),
          file=sys.stderr)
    raise SystemExit(1)
if "choices" not in r:
    print("FAIL: %s: %s" % (model, json.dumps(r)[:300]), file=sys.stderr)
    raise SystemExit(1)
content = ((r["choices"][0].get("message") or {}).get("content") or "").strip()
if not content:
    print("FAIL: %s: 200 OK but empty content (reasoning tokens consumed max_tokens?)"
          % model, file=sys.stderr)
    raise SystemExit(1)
print("OK   %s: %s (usage: %s total tokens)"
      % (model, content[:60].replace("\n", " "),
         (r.get("usage") or {}).get("total_tokens", "n/a")))
PY
  return 0
}

echo "=== GET /models ==="
HTTP="$(curl -sS -m 30 -o "$BODY" -w '%{http_code}' "$BASE/models" \
        -H "Authorization: Bearer $KEY" 2>/dev/null)"
if [ "$HTTP" = "200" ]; then
  python3 - "$BODY" <<'PY' || fail "GET /models returned no usable model list"
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
ids = [m.get("id", "") for m in d.get("data", [])]
print("OK   /models: %d model(s) served" % len(ids))
if not ids:
    raise SystemExit(1)
PY
else
  fail "GET /models: HTTP ${HTTP:-none}"
fi
echo

for M in qwen3.7-plus qwen3.6-plus kimi-k2.5; do
  echo "=== chat: $M ==="
  chat "$M" "{\"model\": \"$M\", \"messages\": [{\"role\": \"user\", \"content\": \"Reply with exactly: OK-$M\"}], \"max_tokens\": 200, \"temperature\": 0}" || true
  echo
done

echo "=== judge smoke: kimi-k2.5 with response_format json_object ==="
JUDGE_PAYLOAD='{"model": "kimi-k2.5", "messages": [{"role": "user", "content": "Return a JSON object {\"verdict\": \"support\", \"confidence\": 0.9} judging this claim: the sky is blue."}], "max_tokens": 400, "temperature": 0, "response_format": {"type": "json_object"}}'
HTTP="$(curl -sS -m 90 -o "$BODY" -w '%{http_code}' "$BASE/chat/completions" \
        -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
        -d "$JUDGE_PAYLOAD" 2>/dev/null)"
if [ "$HTTP" != "200" ]; then
  fail "judge json_object: HTTP ${HTTP:-none} — $(head -c 200 "$BODY")"
else
  python3 - "$BODY" <<'PY' || FAILURES=$((FAILURES + 1))
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
content = ((r["choices"][0].get("message") or {}).get("content") or "").strip()
try:
    parsed = json.loads(content)
    print("OK   judge json_object parses as a dict:", str(parsed)[:120])
    if not isinstance(parsed, dict):
        raise SystemExit(1)
except Exception as exc:
    print("FAIL: judge reply is not a JSON object (%s): %s" % (exc, content[:200]),
          file=sys.stderr)
    raise SystemExit(1)
PY
fi
echo

if [ "$FAILURES" -ne 0 ]; then
  echo "STATUS: FAIL — $FAILURES check(s) failed; do not start a bench run (see docs/benchmarking.md judge protocol)"
  exit 1
fi
echo "STATUS: SUCCESS — generators + judge reachable and the judge emits json_object"
