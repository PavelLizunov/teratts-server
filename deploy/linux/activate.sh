#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

[ "$#" -eq 1 ] || fail "usage: $0 <exact-source-sha>"
require_root
require_command sha256sum
sha=$1
validate_sha "$sha"
release="$RELEASES_ROOT/$sha"
model="$MODELS_ROOT/teratts-v2-$PINNED_MODEL_REVISION"
assert_directory_nosymlink "$release"
assert_regular_nosymlink "$release/teratts-server"
assert_regular_nosymlink "$release/release.env"
assert_directory_nosymlink "$release/lib"
assert_directory_nosymlink "$model"
assert_regular_nosymlink "$model/manifest.json"
assert_regular_nosymlink "$model/SHA256SUMS"
pinned_ort_version=$ORT_VERSION
pinned_ort_dylib_name=$ORT_DYLIB_NAME
pinned_ort_dylib_sha256=$ORT_DYLIB_SHA256

# shellcheck disable=SC1090
. "$release/release.env"
[ "${APP_GIT_SHA:-}" = "$sha" ] || fail "release metadata SHA mismatch"
[ "${TERATTS_EXPECTED_APP_GIT_SHA:-}" = "$sha" ] || fail "runtime expected SHA mismatch"
[ "${MODEL_REVISION:-}" = "$PINNED_MODEL_REVISION" ] || fail "release metadata model revision mismatch"
[ "${ORT_VERSION:-}" = "$pinned_ort_version" ] || fail "release metadata ONNX Runtime version mismatch"
[ "${ORT_DYLIB_NAME:-}" = "$pinned_ort_dylib_name" ] || fail "release metadata ONNX Runtime library mismatch"
[ "${ORT_DYLIB_SHA256:-}" = "$pinned_ort_dylib_sha256" ] || fail "release metadata ONNX Runtime hash mismatch"
[ "${ORT_DYLIB_PATH:-}" = "$RELEASE_CURRENT/lib/$pinned_ort_dylib_name" ] || fail "ORT_DYLIB_PATH must be the approved absolute current-release path"
case "$ORT_DYLIB_PATH" in
    /*) : ;;
    *) fail "ORT_DYLIB_PATH must be absolute" ;;
esac
assert_regular_nosymlink "$release/lib/$pinned_ort_dylib_name"
verify_sha256 "$BINARY_SHA256" "$release/teratts-server"
verify_sha256 "$pinned_ort_dylib_sha256" "$release/lib/$pinned_ort_dylib_name"
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
