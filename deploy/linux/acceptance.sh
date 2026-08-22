#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

require_root
require_command ss
[ -z "${DSH_SESSION_ID:-}" ] && [ -z "${DSH_WEB_URL:-}" ] || fail "run disruptive acceptance from an external management session, never an active DSH session"
"$SYSTEMCTL" is-active --quiet "$SERVICE_NAME" || fail "$SERVICE_NAME is not active"
"$SYSTEMCTL" is-enabled --quiet "$SERVICE_NAME" || fail "$SERVICE_NAME is not enabled"

active=$(read_link_or_empty "$RELEASE_CURRENT")
[ -n "$active" ] || fail "current release link is missing"
sha=$(basename "$active")
validate_sha "$sha"
[ "$active" = "$RELEASES_ROOT/$sha" ] || fail "current release points outside $RELEASES_ROOT"
[ -z "$(find "$active" "$MODELS_ROOT/teratts-v2-$PINNED_MODEL_REVISION" -perm /0222 -print -quit)" ] || fail "active release or model tree is writable"
[ "$(stat -c '%U:%G' "$active/teratts-server")" = root:root ] || fail "binary owner must be root:root"
[ -x "$active/teratts-server" ] || fail "active binary is not executable"
assert_regular_nosymlink "$active/lib/$ORT_DYLIB_NAME"
verify_sha256 "$ORT_DYLIB_SHA256" "$active/lib/$ORT_DYLIB_NAME"
# shellcheck disable=SC1090
. "$active/release.env"
[ "$ORT_DYLIB_PATH" = "$RELEASE_CURRENT/lib/$ORT_DYLIB_NAME" ] || fail "active ORT_DYLIB_PATH is not the approved absolute path"

listeners=$(ss -H -ltnp 'sport = :8088' 2>/dev/null || true)
[ -n "$listeners" ] || fail "no listener on TCP port 8088"
printf '%s\n' "$listeners" | awk '{print $4}' | grep -Ev '^(127\.0\.0\.1|\[::1\]):8088$' >/dev/null && fail "port 8088 is not loopback-only"

"$SCRIPT_DIR/verify-health.sh" "$sha" "$PINNED_MODEL_REVISION"

response=$(mktemp)
trap 'rm -f "$response"' EXIT HUP INT TERM
# shellcheck disable=SC1090
. "$CONFIG_ROOT/teratts.env"
[ -n "${TERATTS_BEARER_TOKEN:-}" ] || fail "TERATTS_BEARER_TOKEN is missing"
unauthorized=$("$CURL" --silent --output /dev/null --write-out '%{http_code}' \
    --header 'Content-Type: application/json' \
    --data '{"text":"Проверка."}' \
    http://127.0.0.1:8088/tts)
[ "$unauthorized" = 401 ] || fail "unauthenticated TTS request returned HTTP $unauthorized"
code=$("$CURL" --silent --show-error --max-time 120 --output "$response" --write-out '%{http_code}' \
    --header 'Content-Type: application/json' \
    --header "Authorization: Bearer $TERATTS_BEARER_TOKEN" \
    --data '{"text":"Проверка.","voice":"ru_f1","language":"ru","duration_scale":1.0}' \
    http://127.0.0.1:8088/tts)
[ "$code" = 200 ] || fail "TTS smoke test returned HTTP $code"
[ "$(stat -c '%s' "$response")" -gt 44 ] || fail "TTS smoke WAV is empty"
[ "$(dd if="$response" bs=1 count=4 2>/dev/null)" = RIFF ] || fail "TTS response lacks RIFF header"
[ "$(dd if="$response" bs=1 skip=8 count=4 2>/dev/null)" = WAVE ] || fail "TTS response lacks WAVE header"
info "acceptance passed: immutable artifacts, service state, loopback listener, health, and WAV smoke test"
