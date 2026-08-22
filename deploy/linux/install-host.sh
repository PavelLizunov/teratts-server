#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

require_root
"$SCRIPT_DIR/preflight.sh"

if ! getent group "$SERVICE_GROUP" >/dev/null; then
    groupadd --system "$SERVICE_GROUP"
fi
if ! getent passwd "$SERVICE_USER" >/dev/null; then
    useradd --system --gid "$SERVICE_GROUP" --home-dir "$STATE_ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -o root -g root -m 0755 /opt/teratts "$RELEASES_ROOT"
install -d -o root -g root -m 0755 "$STATE_ROOT" "$MODELS_ROOT"
install -d -o root -g "$SERVICE_GROUP" -m 0750 "$CONFIG_ROOT"
install -d -o root -g root -m 0755 /usr/local/libexec/teratts

for script in activate.sh acceptance.sh install-model.sh install-release.sh rollback.sh verify-health.sh; do
    install -o root -g root -m 0755 "$SCRIPT_DIR/$script" "/usr/local/libexec/teratts/$script"
done
install -o root -g root -m 0644 "$SCRIPT_DIR/ort-artifact.env" /usr/local/libexec/teratts/ort-artifact.env
install -d -o root -g root -m 0755 /usr/local/libexec/teratts/lib
install -o root -g root -m 0644 "$SCRIPT_DIR/lib/common.sh" /usr/local/libexec/teratts/lib/common.sh
install -o root -g root -m 0644 "$SCRIPT_DIR/systemd/teratts.service" /etc/systemd/system/teratts.service

if [ ! -e "$CONFIG_ROOT/teratts.env" ]; then
    token=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
    umask 027
    {
        printf 'TERATTS_BEARER_TOKEN=%s\n' "$token"
        printf 'TERATTS_RUACCENT_MODE=full\n'
    } > "$CONFIG_ROOT/teratts.env"
    chown root:"$SERVICE_GROUP" "$CONFIG_ROOT/teratts.env"
    chmod 0640 "$CONFIG_ROOT/teratts.env"
fi

"$SYSTEMCTL" daemon-reload
info "host installed; provision external configuration/credentials, then install and activate immutable artifacts"
