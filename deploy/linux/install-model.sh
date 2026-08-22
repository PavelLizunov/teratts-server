#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

[ "$#" -eq 2 ] || fail "usage: $0 <model-revision> <prepared-model-release-dir>"
require_root
require_command sha256sum
revision=$1
source_dir=$2
validate_revision "$revision"
[ "$revision" = "$PINNED_MODEL_REVISION" ] || fail "model revision must match pinned revision $PINNED_MODEL_REVISION"
assert_directory_nosymlink "$source_dir"
[ -f "$source_dir/manifest.json" ] || fail "prepared model directory lacks manifest.json"

expected_name="teratts-v2-$revision"
destination="$MODELS_ROOT/$expected_name"
[ ! -e "$destination" ] || fail "immutable model release already exists: $destination"
install -d -o root -g root -m 0755 "$STATE_ROOT" "$MODELS_ROOT"
staging="$MODELS_ROOT/.${expected_name}.part.$$"
trap 'rm -rf "$staging"' EXIT HUP INT TERM
install -d -o root -g root -m 0755 "$staging"
cp -a "$source_dir/." "$staging/"
find "$staging" -type l -print | grep -q . && fail "model release must not contain symbolic links"
find "$staging" \( -type b -o -type c -o -type p -o -type s \) -print | grep -q . && fail "model release contains a special file"
find "$staging" ! -user root -exec chown root:root {} +
(
    cd "$staging"
    find . -type f ! -name SHA256SUMS -print | LC_ALL=C sort | sed 's#^./##' | xargs -r sha256sum >SHA256SUMS
)
chmod 0444 "$staging/SHA256SUMS"
make_tree_immutable "$staging"
mv "$staging" "$destination"
trap - EXIT HUP INT TERM
info "installed immutable model release: $destination"
