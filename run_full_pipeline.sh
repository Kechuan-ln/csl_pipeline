#!/bin/bash
# =========================================
# Full 17-Camera Pipeline
# Sync → Extract → Stable → Calibrate → YAML → GT Distribution
# =========================================
#
# Usage:
#   ./run_full_pipeline.sh           # Run all steps
#   ./run_full_pipeline.sh --from 3  # Resume from step 3
#
# Steps:
#   0. GT data generation from Motive CSV (optional, run separately if needed)
#   1. GoPro QR sync (16 cameras)
#   2. PrimeColor sync (cam19)
#   3. Extract frames (17 cameras)
#   4. Stable frame detection (17 cameras)
#   5. Extrinsic calibration (17 cameras)
#   6. Generate individual camera YAML
#   7. Distribute GT from cam19 to per-camera gt/ folders
#
# Note: Step 0 (GT generation) is NOT included in the default pipeline
#       because it requires T7 volume and is typically run once separately.
#       Use: ./run_generate_gt.sh
# =========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

START_FROM=1
if [ "$1" = "--from" ] && [ -n "$2" ]; then
    START_FROM=$2
fi

run_step() {
    step_num=$1
    step_name=$2
    step_cmd=$3

    if [ $step_num -lt $START_FROM ]; then
        echo "[Step $step_num] $step_name — SKIPPED (--from $START_FROM)"
        return 0
    fi

    echo ""
    echo "============================================================"
    echo "  Step $step_num: $step_name"
    echo "============================================================"

    eval "$step_cmd"
    status=$?

    if [ $status -ne 0 ]; then
        echo ""
        echo "ERROR: Step $step_num failed! (exit code $status)"
        echo "Fix the issue and resume with: ./run_full_pipeline.sh --from $step_num"
        exit $status
    fi

    echo "[Step $step_num] DONE"
}

echo "========================================="
echo "  Full 17-Camera Pipeline"
echo "  Starting from step $START_FROM"
echo "========================================="

run_step 1 "GoPro QR Sync"         "./run_sync_gopro_batch.sh"
run_step 2 "PrimeColor Sync"       "./run_sync_primecolor_batch.sh"
run_step 3 "Extract Frames"        "./run_extract_frames_parallel.sh"
run_step 4 "Stable Frame Detection" "./run_find_and_copy_stable_auto.sh"
run_step 5 "Extrinsic Calibration" "./run_calibration_stable.sh"
run_step 6 "Individual Camera YAML" "./run_post_calibration.sh"
run_step 7 "GT Distribution"       "./run_distribute_gt.sh --all"

echo ""
echo "========================================="
echo "  Pipeline Complete!"
echo "========================================="
echo ""
echo "Optional next step: Refine extrinsics interactively"
echo "  python post_calibration/refine_extrinsics.py --help"
