#!/usr/bin/env bash
# scan_daily.sh — run scan + backfill tracking + calibration check
# Schedule via crontab: 30 22 * * 1-5 ~/Vibe-Trading/scripts/scan_daily.sh
#   (22:30 Mon-Fri = after US market close in Asia timezone)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_DIR/.venv/bin/python"
CLI="$PROJECT_DIR/agent/cli/_legacy.py"
LOG_DIR="$HOME/.vibe-trading/logs"
SCAN_DIR="$HOME/.vibe-trading/scans"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/scan_$(date +%Y%m%d_%H%M%S).log"

run_cli() {
    cd "$PROJECT_DIR/agent"
    PYTHONPATH=. "$VENV" "$CLI" "$@"
}

{
    echo "=== scan_daily $(date -Iseconds) ==="

    # 1. Today's scan
    TODAY=$(date +%Y-%m-%d)
    echo "[1/3] scan run --asof $TODAY"
    run_cli scan run --asof "$TODAY" || echo "  ⚠ scan run failed (market holiday?)"

    # 2. Backfill tracking for all past scan dates missing forward returns
    echo "[2/3] backfill tracking"
    if [ -d "$SCAN_DIR" ]; then
        for d in "$SCAN_DIR"/*/; do
            asof=$(basename "$d")
            [[ "$asof" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue
            echo "  track --asof $asof"
            run_cli scan track --asof "$asof" || echo "  ⚠ track $asof failed"
        done
    fi

    # 3. Calibration check
    echo "[3/3] calibrate"
    run_cli scan calibrate || true

    echo "=== done $(date -Iseconds) ==="
} >> "$LOG" 2>&1

echo "scan_daily complete — log: $LOG"
