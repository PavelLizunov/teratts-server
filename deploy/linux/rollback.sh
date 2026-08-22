#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

require_root
if [ "$#" -gt 1 ]; then
    fail "usage: $0 [exact-source-sha]"
fi

if [ "$#" -eq 1 ]; then
    target=$1
else
    current=$(read_link_or_empty "$RELEASE_CURRENT")
    [ -n "$current" ] || fail "no active release and no rollback SHA supplied"
    target=$(find "$RELEASES_ROOT" -mindepth 1 -maxdepth 1 -type d ! -name '.*' ! -path "$current" -printf '%T@ %f\n' | sort -nr | awk 'NR == 1 { print $2 }')
    [ -n "$target" ] || fail "no prior immutable release found; provide a SHA explicitly"
fi
validate_sha "$target"
exec "$SCRIPT_DIR/activate.sh" "$target"
