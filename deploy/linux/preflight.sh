#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

require_root

[ -r /etc/os-release ] || fail "/etc/os-release is unavailable"
# shellcheck disable=SC1091
. /etc/os-release
[ "${ID:-}" = debian ] || fail "target must be Debian"
[ "${VERSION_ID:-}" = 12 ] || fail "target must be Debian 12"

[ -d /run/systemd/system ] || fail "systemd is not PID 1"
[ -r /proc/1/uid_map ] || fail "container UID map is unavailable"
first_map=$(awk 'NR == 1 { print $1, $2, $3 }' /proc/1/uid_map)
case "$first_map" in
    "0 0 4294967295") fail "target appears privileged; an unprivileged LXC is required" ;;
    "0 "*) : ;;
    *) fail "unexpected container UID map: $first_map" ;;
esac

for command in curl findmnt getent install ip mv python3 readlink runuser sha256sum ss stat systemctl useradd; do
    require_command "$command"
done

[ "$(findmnt -n -o FSTYPE /)" != overlay ] || fail "overlay root is not an approved deployment target"

if getent passwd "$SERVICE_USER" >/dev/null; then
    shell=$(getent passwd "$SERVICE_USER" | awk -F: '{print $7}')
    case "$shell" in
        /usr/sbin/nologin|/sbin/nologin|/bin/false) : ;;
        *) fail "$SERVICE_USER must have a non-login shell" ;;
    esac
    home=$(getent passwd "$SERVICE_USER" | awk -F: '{print $6}')
    [ "$home" = "$STATE_ROOT" ] || fail "$SERVICE_USER home must be $STATE_ROOT"
else
    info "$SERVICE_USER does not exist yet; install-host.sh will create it"
fi

available_kib=$(df -Pk /opt /var 2>/dev/null | awk 'NR > 1 { if (!seen[$6]++) total += $4 } END { print total + 0 }')
minimum_kib=${TERATTS_MIN_FREE_KIB:-2097152}
[ "$available_kib" -ge "$minimum_kib" ] || fail "at least ${minimum_kib} KiB free across target filesystems is required"

if [ -n "${DSH_SESSION_ID:-}" ] || [ -n "${DSH_WEB_URL:-}" ]; then
    info "DSH session detected: this kit never restarts DSH; service activation affects teratts.service only"
fi

info "preflight passed: Debian 12, unprivileged container map, systemd, tools, and storage"
