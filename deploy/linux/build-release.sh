#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

[ "$#" -eq 2 ] || fail "usage: $0 <exact-source-sha> <output-binary>"
for command in cargo git install sha256sum; do
    require_command "$command"
done
sha=$1
output=$2
validate_sha "$sha"
[ "$(git rev-parse HEAD)" = "$sha" ] || fail "HEAD is not the requested exact source SHA"
[ -z "$(git status --porcelain --untracked-files=no)" ] || fail "tracked working tree must be clean"

TERATTS_APP_GIT_SHA=$sha cargo build --release --locked
install -m 0555 target/release/teratts-server "$output"
info "built exact-SHA release: $output"
sha256sum "$output"
