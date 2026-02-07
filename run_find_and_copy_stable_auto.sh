#!/bin/bash
# Detect stable ChArUco frames and copy union set (17 cameras)
# =========================================
# Usage: ./run_find_and_copy_stable_auto.sh
# =========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/camera_config.sh"

export PATH_ASSETS_VIDEOS=/Volumes/FastACIS/

cd "$SCRIPT_DIR"

###########################################
# Configuration
###########################################

DATA_ROOT="/Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced"
INPUT_SUBDIR="original"
OUTPUT_SUBDIR="original_stable"

# Use all 17 cameras
cameras=("${ALL_CAMERAS[@]}")

# Board config (relative to SCRIPT_DIR)
BOARD_CONFIG="multical/asset/charuco_b1_2.yaml"

# Detection parameters
MOVEMENT_THRESHOLD=5.0
MIN_DETECTION_QUALITY=40
DOWNSAMPLE_RATE=10
MAX_FRAMES=500

###########################################

INPUT_DIR="${DATA_ROOT}/${INPUT_SUBDIR}"
OUTPUT_DIR="${DATA_ROOT}/${OUTPUT_SUBDIR}"
TEMP_RESULTS_DIR="${SCRIPT_DIR}/detection_results_temp"

echo "========================================="
echo "Stable Frame Detection + Union Copy"
echo "========================================="
echo "Input:   $INPUT_DIR"
echo "Output:  $OUTPUT_DIR"
echo "Cameras: ${#cameras[@]} (${cameras[*]})"
echo ""

# Step 1: Parallel stable frame detection
echo "Step 1: Detecting stable frames (parallel)..."
mkdir -p "$TEMP_RESULTS_DIR"

for cam in "${cameras[@]}"; do
    # cam19 (PrimeColor) at 1080p may need different thresholds
    if [[ "$cam" == "cam19" ]]; then
        MVT=$MOVEMENT_THRESHOLD
        MDQ=30
    else
        MVT=$MOVEMENT_THRESHOLD
        MDQ=$MIN_DETECTION_QUALITY
    fi

    echo "  Detecting $cam (threshold=$MVT, quality=$MDQ)..."
    (
        cd "$SCRIPT_DIR"
        python scripts/find_stable_boards.py \
            --recording_tag "$INPUT_DIR" \
            --boards "$BOARD_CONFIG" \
            --movement_threshold $MVT \
            --min_detection_quality $MDQ \
            --downsample_rate $DOWNSAMPLE_RATE \
            --max_frames_per_camera $MAX_FRAMES \
            --cam_filter $cam > "${TEMP_RESULTS_DIR}/${cam}_result.txt" 2>&1
    ) &
done

wait
echo "All cameras detected"
echo ""

# Step 2: Parse results and compute Union
echo "Step 2: Computing Union..."

python - "$INPUT_DIR" "$OUTPUT_DIR" "$TEMP_RESULTS_DIR" << 'PYTHON_SCRIPT'
import re
import json
import shutil
import sys
from pathlib import Path

input_dir_str = sys.argv[1]
output_dir_str = sys.argv[2]
temp_results_dir_str = sys.argv[3]

TEMP_RESULTS_DIR = Path(temp_results_dir_str)
INPUT_DIR = Path(input_dir_str)
OUTPUT_DIR = Path(output_dir_str)

# Parse detection results
stable_frames = {}
result_files = list(TEMP_RESULTS_DIR.glob("*_result.txt"))

print(f"Parsing {len(result_files)} result files...")

for result_file in result_files:
    camera = result_file.stem.replace("_result", "")

    with open(result_file, 'r') as f:
        content = f.read()

    match = re.search(r'Stable frame indices:\s*\[([0-9,\s]*)\]', content)
    if match:
        indices_str = match.group(1).strip()
        if indices_str:
            indices = [int(x.strip()) for x in indices_str.split(',') if x.strip()]
        else:
            indices = []
        stable_frames[camera] = indices
        print(f"  {camera}: {len(indices)} frames")
    else:
        print(f"  {camera}: no stable frames found")
        stable_frames[camera] = []

# Compute Union
union_indices = set()
for camera, indices in stable_frames.items():
    union_indices.update(indices)

union_indices = sorted(union_indices)
print(f"\nUnion: {len(union_indices)} unique frames")

# Save detection summary
detection_summary = {
    'per_camera': stable_frames,
    'union': union_indices,
    'total_union_frames': len(union_indices)
}

summary_file = OUTPUT_DIR.parent / "stable_frames_detection.json"
summary_file.parent.mkdir(parents=True, exist_ok=True)
with open(summary_file, 'w') as f:
    json.dump(detection_summary, f, indent=2)

print(f"Summary saved: {summary_file}")

# Step 3: Copy union frames
print(f"\nStep 3: Copying union frames to {len(stable_frames)} cameras...")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

for camera in stable_frames.keys():
    cam_input_dir = INPUT_DIR / camera
    out_cam_dir = OUTPUT_DIR / camera
    out_cam_dir.mkdir(parents=True, exist_ok=True)

    copied_count = 0
    for frame_idx in union_indices:
        src_files = [
            cam_input_dir / f"frame_{frame_idx:04d}.png",
            cam_input_dir / f"frame_{frame_idx:04d}.jpg",
            cam_input_dir / f"frame_{frame_idx:08d}.png",
            cam_input_dir / f"frame_{frame_idx:08d}.jpg"
        ]

        for src in src_files:
            if src.exists():
                dst = out_cam_dir / src.name
                shutil.copy2(src, dst)
                copied_count += 1
                break

    print(f"  {camera}: copied {copied_count}/{len(union_indices)} frames")

print(f"\nAll frames copied to: {OUTPUT_DIR}")

PYTHON_SCRIPT

# Cleanup
rm -rf "$TEMP_RESULTS_DIR"

echo ""
echo "========================================="
echo "Done!"
echo "========================================="
echo "Stable frames: $OUTPUT_DIR"
echo "Summary: ${DATA_ROOT}/stable_frames_detection.json"
echo ""
echo "Next: ./run_calibration_stable.sh"
