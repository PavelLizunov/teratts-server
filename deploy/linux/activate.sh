#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

[ "$#" -eq 1 ] || fail "usage: $0 <exact-source-sha>"
require_root
sha=$1
validate_sha "$sha"
release="$RELEASES_ROOT/$sha"
model="$MODELS_ROOT/teratts-v2-$PINNED_MODEL_REVISION"
assert_directory_nosymlink "$release"
assert_regular_nosymlink "$release/teratts-server"
assert_regular_nosymlink "$release/release.env"
assert_directory_nosymlink "$model"
assert_regular_nosymlink "$model/manifest.json"
assert_regular_nosymlink "$model/SHA256SUMS"

# shellcheck disable=SC1090
. "$release/release.env"
[ "${APP_GIT_SHA:-}" = "$sha" ] || fail "release metadata SHA mismatch"
[ "${MODEL_REVISION:-}" = "$PINNED_MODEL_REVISION" ] || fail "release metadata model revision mismatch"
printf '%s  %s\n' "$BINARY_SHA256" "$release/teratts-server" | sha256sum -c - >/dev/null
(cd "$model" && sha256sum -c SHA256SUMS >/dev/null)
[ -z "$(find "$release" "$model" -perm /0222 -print -quit)" ] || fail "release or model tree is writable"

old_release=$(read_link_or_empty "$RELEASE_CURRENT")
rollback() {
    info "activation failed; restoring previous release"
    restore_link "$old_release" "$RELEASE_CURRENT"
    if [ -n "$old_release" ]; then
        "$SYSTEMCTL" restart "$SERVICE_NAME" || true
        old_sha=$(basename "$old_release")
        "$SCRIPT_DIR/verify-health.sh" "$old_sha" "$PINNED_MODEL_REVISION" || true
    else
        "$SYSTEMCTL" stop "$SERVICE_NAME" || true
    fi
}
trap 'rollback' EXIT HUP INT TERM

atomic_link "$release" "$RELEASE_CURRENT"
"$SYSTEMCTL" enable "$SERVICE_NAME" >/dev/null
"$SYSTEMCTL" restart "$SERVICE_NAME"
"$SCRIPT_DIR/verify-health.sh" "$sha" "$PINNED_MODEL_REVISION"
trap - EXIT HUP INT TERM
info "activated release: $sha"
