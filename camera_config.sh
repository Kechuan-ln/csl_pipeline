#!/bin/bash
# ============================================================
# Camera configuration for 17-camera system (16 GoPro + 1 PrimeColor)
# Source this file in workflow scripts:
#   source "$(dirname "$0")/camera_config.sh"
# ============================================================

# GoPro cameras (16 cameras, 3840x2160, 60fps)
# Note: cam13 and cam14 are not used in this setup
GOPRO_CAMERAS=(cam1 cam2 cam3 cam4 cam5 cam6 cam7 cam8 cam9 cam10 cam11 cam12 cam15 cam16 cam17 cam18)

# PrimeColor camera (1 camera, 1920x1080, 120fps source → 60fps synced)
PRIMECOLOR_CAMERAS=(cam19)

# All cameras (17 total)
ALL_CAMERAS=("${GOPRO_CAMERAS[@]}" "${PRIMECOLOR_CAMERAS[@]}")

# Recording sets (15 sets)
ALL_SETS=(P4_1 P4_2 P4_3 P4_4 P4_5 P5_1 P5_2 P5_3 P5_4 P5_5 P6_1 P6_2 P6_3 P6_4 P6_5)

# Camera counts
NUM_GOPRO=${#GOPRO_CAMERAS[@]}
NUM_ALL=${#ALL_CAMERAS[@]}
