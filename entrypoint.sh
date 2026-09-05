#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${BORG2MQTT_CONFIG:-/root/.config/borg2mqtt/config.yml}"
SETUP_RETRY_INTERVAL="${SETUP_RETRY_INTERVAL:-3600}"
BORG2MQTT_BIN="$(command -v borg2mqtt)"

log() { echo "[entrypoint] $*"; }

if [ ! -f "$CONFIG_FILE" ]; then
  log "No config found at $CONFIG_FILE, generating a starter config..."
  borg2mqtt -c "$CONFIG_FILE" generate
fi

until borg2mqtt -c "$CONFIG_FILE" setup; do
  log "setup failed (config likely still needs real repo/MQTT values) - retrying in ${SETUP_RETRY_INTERVAL}s..."
  sleep "$SETUP_RETRY_INTERVAL"
done

CHECK_CRON=$(borg2mqtt -c "$CONFIG_FILE" schedule)
log "Scheduling: update hourly, check on '$CHECK_CRON'"

CRON_FILE=/etc/cron.d/borg2mqtt
cat > "$CRON_FILE" <<EOF
PATH=$PATH
MAILTO=""
0 * * * * root $BORG2MQTT_BIN -c "$CONFIG_FILE" update >> /proc/1/fd/1 2>> /proc/1/fd/2
$CHECK_CRON root $BORG2MQTT_BIN -c "$CONFIG_FILE" check >> /proc/1/fd/1 2>> /proc/1/fd/2
EOF
chmod 0644 "$CRON_FILE"

exec cron -f
