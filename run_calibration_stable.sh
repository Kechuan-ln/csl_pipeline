#!/bin/bash
# Extrinsic calibration using stable frames (17 cameras)
# =========================================
# Usage: ./run_calibration_stable.sh
# =========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/camera_config.sh"

export PATH_ASSETS_VIDEOS=/Volumes/FastACIS/

###########################################
# Configuration
###########################################

DATA_ROOT="/Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/"
STABLE_SUBDIR="original_stable"

# Intrinsic file (merged 17-camera intrinsics)
# Use intrinsic_all_17_cameras.json for 17-camera calibration
# Use intrinsic_hyperoff_linear_60fps.json for GoPro-only (16 cameras)
INTRINSIC_FILE="${SCRIPT_DIR}/intrinsic_all_17_cameras.json"

# Board config
BOARD_CONFIG="${SCRIPT_DIR}/multical/asset/charuco_b1_2.yaml"

# Calibration parameters
LIMIT_IMAGES=1000
FIX_INTRINSIC=true
ENABLE_VIS=false

###########################################

IMAGE_PATH="${DATA_ROOT}/${STABLE_SUBDIR}"
OUTPUT_DIR="${IMAGE_PATH}"

cd "${SCRIPT_DIR}/multical"

echo "========================================="
echo "Extrinsic Calibration (${NUM_ALL} cameras)"
echo "========================================="
echo "Image dir:   $IMAGE_PATH"
echo "Intrinsics:  $INTRINSIC_FILE"
echo "Board:       $BOARD_CONFIG"
echo "Fix intrinsic: $FIX_INTRINSIC"
echo "Max images:  $LIMIT_IMAGES"
echo ""

CMD="python calibrate.py"
CMD="$CMD --boards $BOARD_CONFIG"
CMD="$CMD --image_path $IMAGE_PATH"
CMD="$CMD --calibration $INTRINSIC_FILE"
CMD="$CMD --camera_pattern '{camera}'"
CMD="$CMD --limit_images $LIMIT_IMAGES"

if [ "$FIX_INTRINSIC" = true ]; then
    CMD="$CMD --fix_intrinsic"
fi

if [ "$ENABLE_VIS" = true ]; then
    CMD="$CMD --vis"
fi

echo "Running: $CMD"
echo ""

eval $CMD

echo ""
echo "========================================="
echo "Calibration complete!"
echo "========================================="
echo "Output: ${OUTPUT_DIR}/calibration.json"
echo ""
echo "Next: ./run_post_calibration.sh"
