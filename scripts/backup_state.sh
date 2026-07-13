#!/bin/sh
# Daily backup of ~/.vibe-trading state for the com.vibetrading.backup
# launchd job.
#
# The scanner's forward-return backfill (opportunity_center.db) is
# point-in-time data that cannot be regenerated after loss — it is the
# system's self-validation record and the most valuable artifact on disk.
#
# Layout under $VIBE_BACKUP_DEST (default ~/Backups/vibe-trading):
#   daily/YYYY-MM-DD/*.db   consistent SQLite snapshots (sqlite3 .backup —
#                           rsync of a live WAL database can tear), pruned
#                           after $RETENTION_DAYS
#   mirror/                 rsync mirror of the remaining state files
#
# Excluded: cache/ + fonts/ (rebuildable, ~270 MB), logs, live/ + .env
# (secrets stay off backup destinations that may sync to cloud storage).
#
# Point VIBE_BACKUP_DEST at an external volume or iCloud Drive for real
# disaster protection; the default only survives deletion/corruption, not
# disk failure.

SRC="${VIBE_BACKUP_SRC:-$HOME/.vibe-trading}"
DEST="${VIBE_BACKUP_DEST:-$HOME/Backups/vibe-trading}"
LOG_FILE="${VIBE_BACKUP_LOG:-$SRC/logs/backup.log}"
RETENTION_DAYS="${VIBE_BACKUP_RETENTION_DAYS:-30}"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
}

mkdir -p "$(dirname "$LOG_FILE")"

# Cap the log at ~256 KB so it can never grow unbounded (same convention as
# the watchdog).
if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 262144 ]; then
    tail -c 131072 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

if [ ! -d "$SRC" ]; then
    log "ERROR: source $SRC does not exist; nothing to back up"
    exit 1
fi

STAMP="$(date '+%Y-%m-%d')"
DAILY="$DEST/daily/$STAMP"
mkdir -p "$DAILY" "$DEST/mirror" || { log "ERROR: cannot create $DEST"; exit 1; }

fails=0

# 1. Consistent snapshots of every top-level SQLite database.
for db in "$SRC"/*.db; do
    [ -f "$db" ] || continue
    name="$(basename "$db")"
    if sqlite3 "$db" ".backup '$DAILY/$name'" 2>>"$LOG_FILE"; then
        :
    else
        fails=$((fails + 1))
        log "ERROR: sqlite backup failed for $name"
    fi
done

# 2. Mirror the rest of the state (reports, scans, tracking, analyses...).
if rsync -a --delete \
    --exclude 'cache/' \
    --exclude 'fonts/' \
    --exclude 'logs/' \
    --exclude 'live/' \
    --exclude '.env' \
    --exclude '*.log' \
    --exclude '*.db' \
    --exclude '*.db-wal' \
    --exclude '*.db-shm' \
    "$SRC/" "$DEST/mirror/" 2>>"$LOG_FILE"; then
    :
else
    fails=$((fails + 1))
    log "ERROR: rsync mirror failed"
fi

# 3. Prune dated snapshots beyond the retention window.
find "$DEST/daily" -mindepth 1 -maxdepth 1 -type d -mtime "+$RETENTION_DAYS" \
    -exec rm -rf {} + 2>>"$LOG_FILE"

size="$(du -sh "$DAILY" 2>/dev/null | cut -f1)"
if [ "$fails" -eq 0 ]; then
    log "OK: snapshot $STAMP ($size) + mirror refreshed at $DEST"
else
    log "DONE WITH $fails ERROR(S): snapshot $STAMP ($size) at $DEST"
fi
exit "$fails"
