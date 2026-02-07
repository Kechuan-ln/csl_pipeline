#!/bin/bash
# =========================================
# GT Data Generation from Motive CSV
# =========================================
#
# Generates ground truth NPY files from OptiTrack Motive CSV exports:
#   1. skeleton_h36m.npy  — 17-joint H36M skeleton (N, 17, 3)
#   2. blade_edges.npy    — Blade ruled surface edges (N, E, 2, 3)
#   3. body_markers.npy   — 27 Plug-in Gait markers (N, 27, 3)
#
# Prerequisites:
#   - csv_structures.json at BASE_DIR (run batch_analyze_csv.py if missing)
#   - blade_polygon_order.json per dataset (manual edge definition step)
#   - Motive CSV exports in BASE_DIR/{SESSION}/
#
# Usage:
#   ./run_generate_gt.sh                    # Run all 3 steps for all sessions
#   ./run_generate_gt.sh --only P4_1,P4_2   # Only specific sessions
#   ./run_generate_gt.sh --step skeleton     # Only skeleton generation
#   ./run_generate_gt.sh --step blade        # Only blade extraction
#   ./run_generate_gt.sh --step markers      # Only marker extraction
#   ./run_generate_gt.sh --dry-run           # Preview commands
#
# Note: P5_1 is auto-skipped (no L/R marker naming).
#       To process P5_1 manually:
#       python scripts/csv2h36m.py /Volumes/T7/csl/P5_1/Take*.csv \
#           --amputation right_leg -o /Volumes/T7/csl/P5_1/skeleton_h36m.npy
# =========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Default paths
BASE_DIR="/Volumes/T7/csl"
STEP="all"
EXTRA_ARGS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --base)
            BASE_DIR="$2"; shift 2 ;;
        --step)
            STEP="$2"; shift 2 ;;
        --only)
            EXTRA_ARGS="$EXTRA_ARGS --only $2"; shift 2 ;;
        --skip)
            EXTRA_ARGS="$EXTRA_ARGS --skip $2"; shift 2 ;;
        --dry-run)
            EXTRA_ARGS="$EXTRA_ARGS --dry-run"; shift ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--base DIR] [--step skeleton|blade|markers|all] [--only P4_1,...] [--dry-run]"
            exit 1 ;;
    esac
done

echo "========================================="
echo "  GT Data Generation"
echo "  Base: $BASE_DIR"
echo "  Step: $STEP"
echo "========================================="
echo ""

if [ ! -f "$BASE_DIR/csv_structures.json" ]; then
    echo "ERROR: csv_structures.json not found at $BASE_DIR"
    echo "Run batch_analyze_csv.py first to generate it."
    exit 1
fi

run_step() {
    local step_name="$1"
    local step_cmd="$2"

    echo ""
    echo "============================================================"
    echo "  $step_name"
    echo "============================================================"

    eval "$step_cmd"
    local status=$?

    if [ $status -ne 0 ]; then
        echo ""
        echo "WARNING: $step_name had failures (exit code $status)"
        echo "Check output above for details."
    fi

    return $status
}

# Step 1: skeleton_h36m.npy
if [ "$STEP" = "all" ] || [ "$STEP" = "skeleton" ]; then
    run_step "Skeleton H36M Generation" \
        "python scripts/batch_csv2h36m.py --base '$BASE_DIR' $EXTRA_ARGS"
fi

# Step 2: blade_edges.npy
if [ "$STEP" = "all" ] || [ "$STEP" = "blade" ]; then
    run_step "Blade Edge Extraction" \
        "python scripts/batch_extract_blade_edges.py --base '$BASE_DIR' $EXTRA_ARGS"
fi

# Step 3: body_markers.npy
if [ "$STEP" = "all" ] || [ "$STEP" = "markers" ]; then
    run_step "Body Marker Extraction" \
        "python scripts/batch_extract_markers.py --base '$BASE_DIR' --legs $EXTRA_ARGS"
fi

echo ""
echo "========================================="
echo "  GT Data Generation Complete"
echo "========================================="
echo ""
echo "Output files per session in $BASE_DIR/{SESSION}/:"
echo "  - skeleton_h36m.npy  (N, 17, 3) float64"
echo "  - blade_edges.npy    (N, E, 2, 3) float32"
echo "  - body_markers.npy   (N, 27, 3) float32"
echo ""
echo "Next step: Symlink GT data and distribute to per-camera folders"
echo "  ./run_distribute_gt.sh --all"
