#!/bin/bash
# Generate individual camera YAML files after calibration
# =========================================
# Usage: ./run_post_calibration.sh
# =========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/camera_config.sh"

###########################################
# Configuration
###########################################

DATA_ROOT="/Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced"
CALIB_JSON="${DATA_ROOT}/original_stable/calibration.json"
CAM19_YAML="/Volumes/FastACIS/csl_11_5/P1/cam19.yaml"
OUTPUT_DIR="${DATA_ROOT}/individual_cam_params"

###########################################

cd "$SCRIPT_DIR"

echo "========================================="
echo "Post-Calibration: Generate Individual YAML"
echo "========================================="
echo "Calibration: $CALIB_JSON"
echo "cam19 yaml:  $CAM19_YAML"
echo "Output:      $OUTPUT_DIR"
echo ""

python post_calibration/generate_individual_cam_yaml.py \
    --calib_json "$CALIB_JSON" \
    --cam19_yaml "$CAM19_YAML" \
    --output_dir "$OUTPUT_DIR"

echo ""
echo "========================================="
echo "Done!"
echo "========================================="
echo ""
echo "To refine individual cameras interactively:"
echo "  python post_calibration/refine_gopro_json.py --help"
