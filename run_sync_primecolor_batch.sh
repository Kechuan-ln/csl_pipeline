#!/bin/bash
# Batch PrimeColor (cam19) sync to GoPro timeline
# =========================================
# Usage: ./run_sync_primecolor_batch.sh [SET1 SET2 ...]
# =========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/camera_config.sh"

###########################################
# Configuration
###########################################

SYNCED_BASE="/Volumes/FastACIS/csl_11_5/synced"
PRIMECOLOR_BASE="/Volumes/T7/csl"

###########################################

cd "$SCRIPT_DIR"

# Use command line args or default to ALL_SETS
EXTRA_ARGS=""
if [ $# -gt 0 ]; then
    EXTRA_ARGS="--sets $*"
fi

echo "========================================="
echo "Batch PrimeColor (cam19) Sync"
echo "========================================="
echo "Synced base:     $SYNCED_BASE"
echo "PrimeColor base: $PRIMECOLOR_BASE"
echo ""

python sync/batch_sync_primecolor.py \
    --synced_base "$SYNCED_BASE" \
    --primecolor_base "$PRIMECOLOR_BASE" \
    $EXTRA_ARGS

echo ""
echo "Next: ./run_extract_frames_parallel.sh"
