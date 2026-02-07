#!/bin/bash
# Batch GoPro QR sync for all recording sets
# =========================================
# Usage: ./run_sync_gopro_batch.sh [SET1 SET2 ...]
# =========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/camera_config.sh"

###########################################
# Configuration
###########################################

ANCHOR_VIDEO="/Volumes/FastACIS/csl_11_5/organized/qr_sync.mp4"
INPUT_BASE="/Volumes/FastACIS/csl_11_5/organized"
OUTPUT_BASE="/Volumes/FastACIS/csl_11_5/synced"

###########################################

cd "$SCRIPT_DIR"

# Use command line args or default to ALL_SETS
if [ $# -gt 0 ]; then
    SETS=("$@")
else
    SETS=("${ALL_SETS[@]}")
fi

echo "========================================="
echo "Batch GoPro QR Sync"
echo "========================================="
echo "Sets: ${SETS[*]}"
echo "Anchor: $ANCHOR_VIDEO"
echo ""

SUCCESS=0
FAIL=0
SKIP=0

for set in "${SETS[@]}"; do
    OUTPUT_DIR="${OUTPUT_BASE}/${set}_sync/cameras_synced"

    if [ -f "${OUTPUT_DIR}/meta_info.json" ]; then
        echo "[${set}] Already synced, skipping"
        ((SKIP++))
        continue
    fi

    echo "[${set}] Syncing..."
    python sync/sync_gopro_qr_fast.py \
        --input_dir "${INPUT_BASE}/${set}" \
        --output_dir "$OUTPUT_DIR" \
        --anchor_video "$ANCHOR_VIDEO" \
        --prefix "" \
        --verify

    if [ $? -eq 0 ]; then
        echo "[${set}] SUCCESS"
        ((SUCCESS++))
    else
        echo "[${set}] FAILED"
        ((FAIL++))
    fi
done

echo ""
echo "========================================="
echo "Summary: ${#SETS[@]} sets, $SUCCESS success, $SKIP skipped, $FAIL failed"
echo "========================================="
echo ""
echo "Next: ./run_sync_primecolor_batch.sh"
