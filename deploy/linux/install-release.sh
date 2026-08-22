#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

[ "$#" -eq 2 ] || fail "usage: $0 <exact-source-sha> <teratts-server-binary>"
require_root
require_command sha256sum
sha=$1
artifact=$2
validate_sha "$sha"
assert_regular_nosymlink "$artifact"
[ -x "$artifact" ] || fail "artifact is not executable: $artifact"

install -d -o root -g root -m 0755 /opt/teratts "$RELEASES_ROOT"
destination="$RELEASES_ROOT/$sha"
[ ! -e "$destination" ] || fail "immutable release already exists: $destination"
staging="$RELEASES_ROOT/.${sha}.part.$$"
trap 'rm -rf "$staging"' EXIT HUP INT TERM
install -d -o root -g root -m 0755 "$staging"
install -o root -g root -m 0555 "$artifact" "$staging/teratts-server"
binary_sha256=$(sha256sum "$staging/teratts-server" | awk '{print $1}')
cat >"$staging/release.env" <<EOF
APP_GIT_SHA=$sha
BINARY_SHA256=$binary_sha256
MODEL_REVISION=$PINNED_MODEL_REVISION
EOF
chmod 0444 "$staging/release.env"
make_tree_immutable "$staging"
mv "$staging" "$destination"
trap - EXIT HUP INT TERM
info "installed immutable release: $destination"
info "binary sha256: $binary_sha256"
