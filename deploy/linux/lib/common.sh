#!/bin/sh
set -eu

RELEASES_ROOT=${TERATTS_RELEASES_ROOT:-/opt/teratts/releases}
RELEASE_CURRENT=${TERATTS_RELEASE_CURRENT:-/opt/teratts/current}
MODELS_ROOT=${TERATTS_MODELS_ROOT:-/var/lib/teratts/models}
STATE_ROOT=${TERATTS_STATE_ROOT:-/var/lib/teratts}
PINNED_MODEL_REVISION=${TERATTS_PINNED_MODEL_REVISION:-f05ea799094571a3553904a555df3834fb0b963b}
CONFIG_ROOT=${TERATTS_CONFIG_ROOT:-/etc/teratts}
SERVICE_NAME=teratts.service
SYSTEMCTL=${SYSTEMCTL:-systemctl}
CURL=${CURL:-curl}
HEALTH_URL=${TERATTS_HEALTH_URL:-http://127.0.0.1:8088/health}
SERVICE_USER=${TERATTS_SERVICE_USER:-teratts}
SERVICE_GROUP=${TERATTS_SERVICE_GROUP:-teratts}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

info() {
    printf '%s\n' "$*"
}

require_root() {
    [ "$(id -u)" -eq 0 ] || fail "run as root"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

validate_sha() {
    value=$1
    case "$value" in
        *[!0-9a-f]*|'') fail "SHA must be lowercase hexadecimal: $value" ;;
    esac
    [ "${#value}" -eq 40 ] || fail "SHA must contain exactly 40 hex characters"
}

validate_revision() {
    value=$1
    case "$value" in
        *[!0-9a-f]*|'') fail "model revision must be lowercase hexadecimal: $value" ;;
    esac
    [ "${#value}" -eq 40 ] || fail "model revision must contain exactly 40 hex characters"
}

assert_regular_nosymlink() {
    [ -f "$1" ] || fail "regular file not found: $1"
    [ ! -L "$1" ] || fail "symbolic-link input is not allowed: $1"
}

assert_directory_nosymlink() {
    [ -d "$1" ] || fail "directory not found: $1"
    [ ! -L "$1" ] || fail "symbolic-link input is not allowed: $1"
}

atomic_link() {
    atomic_target=$1
    atomic_link_path=$2
    atomic_parent=$(dirname "$atomic_link_path")
    atomic_base=$(basename "$atomic_link_path")
    atomic_tmp="$atomic_parent/.${atomic_base}.new.$$"
    mkdir -p "$atomic_parent"
    rm -f "$atomic_tmp"
    ln -s "$atomic_target" "$atomic_tmp"
    mv -Tf "$atomic_tmp" "$atomic_link_path"
}

read_link_or_empty() {
    if [ -L "$1" ]; then
        readlink -f "$1" 2>/dev/null || true
    fi
}

restore_link() {
    old=$1
    link=$2
    if [ -n "$old" ]; then
        atomic_link "$old" "$link"
    else
        rm -f "$link"
    fi
}

make_tree_immutable() {
    find "$1" -type d -exec chmod 0555 {} +
    find "$1" -type f -exec chmod 0444 {} +
}

health_json() {
    "$CURL" --fail --silent --show-error --max-time "${TERATTS_HEALTH_TIMEOUT:-10}" "$HEALTH_URL"
}

json_field() {
    python3 -c 'import json,sys
obj=json.load(sys.stdin)
for key in sys.argv[1].split("|"):
    if key in obj:
        value=obj[key]
        print(value if not isinstance(value,(dict,list)) else json.dumps(value,separators=(",",":")))
        raise SystemExit(0)
raise SystemExit(1)' "$1"
}
