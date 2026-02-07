#!/bin/bash
# Distribute GT data from cam19 to per-camera gt/ folders
# =========================================
# Usage:
#   ./run_distribute_gt.sh                    # Process default session
#   ./run_distribute_gt.sh P4_1 P6_4          # Process specific sessions
#   ./run_distribute_gt.sh --all              # Process all sessions
# =========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/camera_config.sh"

cd "$SCRIPT_DIR"

###########################################
# Configuration
###########################################

SYNCED_BASE="/Volumes/FastACIS/csl_11_5/synced"

###########################################

# Parse arguments
if [ "$1" = "--all" ]; then
    SETS=("${ALL_SETS[@]}")
elif [ $# -gt 0 ]; then
    SETS=("$@")
else
    echo "Usage: ./run_distribute_gt.sh [SESSION...] | --all"
    echo "  Sessions: ${ALL_SETS[*]}"
    exit 1
fi

echo "========================================="
echo "GT Distribution: cam19 → per-camera"
echo "========================================="
echo "Sets: ${SETS[*]}"
echo ""

SUCCESS=0
FAIL=0
SKIP=0

for set in "${SETS[@]}"; do
    SESSION_DIR="${SYNCED_BASE}/${set}_sync/cameras_synced"

    if [ ! -d "$SESSION_DIR" ]; then
        echo "[${set}] cameras_synced/ not found, skipping"
        ((SKIP++))
        continue
    fi

    if [ ! -f "${SESSION_DIR}/cam19/skeleton_h36m.npy" ]; then
        echo "[${set}] cam19/skeleton_h36m.npy not found, skipping"
        ((SKIP++))
        continue
    fi

    echo "[${set}] Distributing GT..."
    python scripts/distribute_gt.py \
        --session_dir "$SESSION_DIR"

    if [ $? -eq 0 ]; then
        echo "[${set}] SUCCESS"
        ((SUCCESS++))
    else
        echo "[${set}] FAILED"
        ((FAIL++))
    fi
    echo ""
done

echo "========================================="
echo "Summary: ${#SETS[@]} sets, $SUCCESS success, $SKIP skipped, $FAIL failed"
echo "========================================="
