#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

expected_sha=${1:-}
expected_revision=${2:-$PINNED_MODEL_REVISION}
[ -z "$expected_sha" ] || validate_sha "$expected_sha"
validate_revision "$expected_revision"

attempts=${TERATTS_HEALTH_ATTEMPTS:-30}
delay=${TERATTS_HEALTH_DELAY:-1}
timeout=${TERATTS_HEALTH_TIMEOUT:-10}
last_error="health endpoint did not become ready"
last_http_code=""
last_curl_error=""
last_body=""

tmp_body=$(mktemp)
tmp_err=$(mktemp)
cleanup() {
    rm -f "$tmp_body" "$tmp_err"
}
trap cleanup EXIT HUP INT TERM

while [ "$attempts" -gt 0 ]; do
    : > "$tmp_body"
    : > "$tmp_err"
    # Query without --fail so error JSON bodies (e.g. 503) are preserved for diagnostics
    if http_code=$("$CURL" --silent --show-error --max-time "$timeout" \
        --output "$tmp_body" --write-out '%{http_code}' "$HEALTH_URL" 2>"$tmp_err"); then
        last_http_code="$http_code"
        if [ "$http_code" = "200" ]; then
            body=$(cat "$tmp_body")
            last_body="$body"
            py_status=$(printf '%s' "$body" | python3 -c 'import json,sys
try:
    obj = json.load(sys.stdin)
except Exception as e:
    sys.stderr.write(f"invalid JSON: {e}\n")
    sys.exit(2)
status = obj.get("status")
if status in ("ready", {"ready": True}):
    sys.exit(0)
sys.stderr.write(f"status={status!r}, verification={obj.get(\"verification\")!r}\n")
sys.exit(1)
' 2>&1 || true)
            py_exit=$?
            if [ "$py_exit" -eq 0 ]; then
                revision=$(printf '%s' "$body" | json_field 'model_revision|revision' 2>/dev/null || true)
                [ "$revision" = "$expected_revision" ] || fail "health model revision $revision != expected $expected_revision"
                if [ -n "$expected_sha" ]; then
                    app_sha=$(printf '%s' "$body" | json_field 'app_git_sha' 2>/dev/null || true)
                    [ -n "$app_sha" ] || fail "health response does not expose required app_git_sha"
                    [ "$app_sha" = "$expected_sha" ] || fail "health app SHA $app_sha != expected $expected_sha"
                fi
                info "health verified: $HEALTH_URL"
                exit 0
            else
                last_error="health JSON did not report ready: $py_status"
            fi
        else
            body=$(head -c 512 "$tmp_body" 2>/dev/null || true)
            last_body="$body"
            last_error="health endpoint returned HTTP $http_code (body: ${body:-<empty>})"
        fi
    else
        curl_exit=$?
        err_msg=$(cat "$tmp_err")
        last_curl_error="$err_msg"
        last_error="curl failed (exit $curl_exit): ${err_msg:-unknown error}"
    fi
    attempts=$((attempts - 1))
    [ "$attempts" -eq 0 ] || sleep "$delay"
done

# Detailed diagnostic reporting on failure
printf 'error: %s\n' "$last_error" >&2
[ -z "$last_http_code" ] || printf 'error: last HTTP status code: %s\n' "$last_http_code" >&2
[ -z "$last_curl_error" ] || printf 'error: last curl error: %s\n' "$last_curl_error" >&2
[ -z "$last_body" ] || printf 'error: last response body: %s\n' "$last_body" >&2

if command -v "$SYSTEMCTL" >/dev/null 2>&1; then
    svc_state=$("$SYSTEMCTL" is-active "$SERVICE_NAME" 2>/dev/null || true)
    svc_substate=$("$SYSTEMCTL" show -p SubState --value "$SERVICE_NAME" 2>/dev/null || true)
    printf 'error: %s systemd state: active=%s, substate=%s\n' "$SERVICE_NAME" "${svc_state:-unknown}" "${svc_substate:-unknown}" >&2
fi

fail "health verification failed for $HEALTH_URL (${TERATTS_HEALTH_ATTEMPTS:-30} attempts exhausted)"
