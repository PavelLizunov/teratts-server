#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

[ "$#" -eq 3 ] || fail "usage: $0 <exact-source-sha> <teratts-server-binary> <${ORT_ARCHIVE_NAME}>"
require_root
for command in awk install sha256sum tar; do
    require_command "$command"
done
sha=$1
artifact=$2
ort_archive=$3
validate_sha "$sha"
assert_regular_nosymlink "$artifact"
assert_regular_nosymlink "$ort_archive"
[ -x "$artifact" ] || fail "artifact is not executable: $artifact"
verify_sha256 "$ORT_ARCHIVE_SHA256" "$ort_archive"

install -d -o root -g root -m 0755 /opt/teratts "$RELEASES_ROOT"
destination="$RELEASES_ROOT/$sha"
[ ! -e "$destination" ] || fail "immutable release already exists: $destination"
staging="$RELEASES_ROOT/.${sha}.part.$$"
trap 'rm -rf "$staging"' EXIT HUP INT TERM
install -d -o root -g root -m 0755 "$staging" "$staging/lib"
install -o root -g root -m 0555 "$artifact" "$staging/teratts-server"
tar -xOf "$ort_archive" "$ORT_ARCHIVE_ROOT/lib/$ORT_DYLIB_NAME" >"$staging/lib/$ORT_DYLIB_NAME"
chmod 0444 "$staging/lib/$ORT_DYLIB_NAME"
verify_sha256 "$ORT_DYLIB_SHA256" "$staging/lib/$ORT_DYLIB_NAME"

binary_sha256=$(sha256sum "$staging/teratts-server" | awk '{print $1}')
cat >"$staging/release.env" <<EOF
APP_GIT_SHA=$sha
TERATTS_EXPECTED_APP_GIT_SHA=$sha
BINARY_SHA256=$binary_sha256
MODEL_REVISION=$PINNED_MODEL_REVISION
ORT_VERSION=$ORT_VERSION
ORT_DYLIB_NAME=$ORT_DYLIB_NAME
ORT_DYLIB_SHA256=$ORT_DYLIB_SHA256
ORT_DYLIB_PATH=$RELEASE_CURRENT/lib/$ORT_DYLIB_NAME
EOF
chmod 0444 "$staging/release.env"
make_tree_immutable "$staging"
chmod 0555 "$staging/teratts-server"
[ -x "$staging/teratts-server" ] || fail "immutable release binary lost executable permission"
mv "$staging" "$destination"
trap - EXIT HUP INT TERM
info "installed immutable release: $destination"
info "binary sha256: $binary_sha256"
info "ONNX Runtime dylib sha256: $ORT_DYLIB_SHA256"
