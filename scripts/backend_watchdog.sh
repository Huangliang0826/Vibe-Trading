#!/bin/sh
# Backend health watchdog for the com.vibetrading.backend launchd service.
#
# launchd's KeepAlive only notices a dead *process* — it cannot detect a hung
# backend that still holds the port but resets every connection (observed
# 2026-07-09: event loop wedged after "opportunity scheduler refresh failed:
# unable to open database file"). This script probes /api/health; after two
# consecutive failures it kickstarts the service.
#
# Installed via ~/Library/LaunchAgents/com.vibetrading.watchdog.plist
# (StartInterval 300). Env overrides exist so the logic is testable without
# touching the real service.

HEALTH_URL="${VIBE_WATCHDOG_URL:-http://127.0.0.1:8899/api/health}"
SERVICE="${VIBE_WATCHDOG_SERVICE:-com.vibetrading.backend}"
STATE_FILE="${VIBE_WATCHDOG_STATE:-$HOME/.vibe-trading/watchdog.failcount}"
LOG_FILE="${VIBE_WATCHDOG_LOG:-$HOME/.vibe-trading/watchdog.log}"
THRESHOLD=2

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
}

# Cap the log at ~256 KB so it can never grow unbounded.
if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 262144 ]; then
    tail -c 131072 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$HEALTH_URL" 2>/dev/null)

if [ "$code" = "200" ]; then
    # Healthy: reset the failure counter; only log when recovering from failures.
    if [ -f "$STATE_FILE" ]; then
        rm -f "$STATE_FILE"
        log "recovered: health 200, failure counter reset"
    fi
    exit 0
fi

fails=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
fails=$((fails + 1))
echo "$fails" > "$STATE_FILE"
log "health check failed (HTTP ${code:-000}), consecutive failures: $fails/$THRESHOLD"

if [ "$fails" -ge "$THRESHOLD" ]; then
    log "restarting $SERVICE via launchctl kickstart -k"
    launchctl kickstart -k "gui/$(id -u)/$SERVICE" >> "$LOG_FILE" 2>&1
    rm -f "$STATE_FILE"
fi
