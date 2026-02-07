#!/bin/bash
# Extract frames from synced videos (17 cameras)
# =========================================
# Usage: ./run_extract_frames_parallel.sh
# =========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/camera_config.sh"

export PATH_ASSETS_VIDEOS=/Volumes/FastACIS/
cd "$SCRIPT_DIR"

###########################################
# Configuration
###########################################

MAX_PARALLEL=5
SRC_TAG="/Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced"
FPS=5
START_SEC=334
DURATION=292

# Use all 17 cameras (16 GoPro + 1 PrimeColor)
cameras=("${ALL_CAMERAS[@]}")

###########################################

process_camera() {
    cam=$1

    TARGET_DIR="${SRC_TAG}/original/$cam"

    if [ -d "$TARGET_DIR" ]; then
        IMAGE_COUNT=$(ls "$TARGET_DIR"/*.jpg 2>/dev/null | wc -l)
        if [ "$IMAGE_COUNT" -gt 10 ]; then
            echo "[$cam] Already has $IMAGE_COUNT images, skipping"
            return 0
        fi
    fi

    echo "[$cam] Starting extraction..."
    python scripts/convert_video_to_images.py \
      --src_tag "$SRC_TAG" \
      --cam_tags $cam \
      --fps $FPS \
      --ss $START_SEC \
      --duration $DURATION \
      --format jpg \
      --quality 2 2>&1 | sed "s/^/[$cam] /"
    echo "[$cam] Done!"
}

echo "========================================="
echo "Frame Extraction (${#cameras[@]} cameras)"
echo "========================================="
echo "Source: $SRC_TAG"
echo "FPS=$FPS, Start=${START_SEC}s, Duration=${DURATION}s"
echo "Cameras: ${cameras[*]}"
echo ""

count=0
for cam in "${cameras[@]}"; do
    process_camera $cam &
    ((count++))
    if (( count % MAX_PARALLEL == 0 )); then
        echo "Waiting for batch to complete..."
        wait
    fi
done

wait
echo "All ${#cameras[@]} cameras processed!"
