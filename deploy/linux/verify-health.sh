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
last_error="health endpoint did not become ready"
while [ "$attempts" -gt 0 ]; do
    if body=$(health_json 2>/dev/null); then
        if printf '%s' "$body" | python3 -c 'import json,sys
obj=json.load(sys.stdin)
status=obj.get("status")
if status not in ("ready", {"ready": True}):
    raise SystemExit("status is not ready")
' 2>/dev/null; then
            revision=$(printf '%s' "$body" | json_field 'model_revision|revision' 2>/dev/null || true)
            [ "$revision" = "$expected_revision" ] || fail "health model revision $revision != expected $expected_revision"
            if [ -n "$expected_sha" ]; then
                app_sha=$(printf '%s' "$body" | json_field 'app_git_sha' 2>/dev/null || true)
                [ -n "$app_sha" ] || fail "health response does not expose required app_git_sha"
                [ "$app_sha" = "$expected_sha" ] || fail "health app SHA $app_sha != expected $expected_sha"
            fi
            info "health verified: $HEALTH_URL"
            exit 0
        fi
        last_error="health JSON did not report ready"
    fi
    attempts=$((attempts - 1))
    [ "$attempts" -eq 0 ] || sleep "$delay"
done
fail "$last_error"
