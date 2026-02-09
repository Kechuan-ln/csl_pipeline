# CSL Pipeline Complete Workflow Guide (P7)

Complete multi-camera calibration and GT distribution for one participant, from raw data to final output.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Data Preparation](#data-preparation)
3. [Pipeline Overview](#pipeline-overview)
4. [Three Pipeline Phases](#three-pipeline-phases)
5. [Verification and Optimization Tools](#verification-and-optimization-tools)
6. [Output Directory Structure](#output-directory-structure)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Software Environment

```bash
# Conda environment
conda activate camcalib

# Verify pyzbar acceleration is available
python -c "from pyzbar import pyzbar; print('✅ pyzbar installed')"
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"
```

### Hardware Resources

- **Storage**: ~30-50 GB per session (GoPro 4K videos + processing outputs)
- **Memory**: 32 GB+ recommended (multi-camera parallel processing)
- **External Storage**:
  - FastACIS: GoPro raw data + sync outputs + calibration results
  - T7/KINGSTON: Mocap raw data + GT outputs

---

## Data Preparation

### 1. Mocap Raw Data Placement

**Location**: `/Volumes/KINGSTON/P7_mocap/`

**Directory Structure**:
```
P7_mocap/
├── P7_1/
│   ├── session1-Camera 13 (C11764).avi       # PrimeColor video (may have multiple segments)
│   ├── session1-Camera 13 (C11764) (1).avi   # Continuation segment
│   └── Take 2024-11-05 03.50.49 PM.csv       # Motive exported CSV
├── P7_2/
│   ├── session2-Camera 13 (C11764).avi
│   └── Take 2024-11-05 04.10.22 PM.csv
├── P7_3/, P7_4/, P7_5/
└── Cal_2026-02-01.mcal                        # OptiTrack calibration file (optional, in parent dir)
```

**Key Files**:
- **AVI videos**: PrimeColor camera raw recordings (120fps, 1920x1080)
- **CSV files**: Motive exported skeleton and marker data
- **.mcal file**: OptiTrack system calibration (contains cam19 initial extrinsics)

---

### 2. GoPro Raw Data Placement

**Location**: `/Volumes/FastACIS/csl_11_5/P7_gopro/`

**Raw Structure** (per-camera):
```
P7_gopro/
├── cam1/
│   ├── GX010279.MP4  # Session 1
│   ├── GX010280.MP4  # Session 2
│   ├── GX010281.MP4  # Session 3
│   └── ...
├── cam2/
│   ├── GX010276.MP4  # Session 1
│   ├── GX010277.MP4  # Session 2
│   └── ...
├── cam3/, ..., cam18/
└── qr_sync.mp4        # QR anchor video (for synchronization)
```

**Note**:
- GoPro filenames auto-increment by **recording time order**, need to map to actual sessions
- Ensure consistent video count per camera (typically 5 sessions = 5 videos)

---

### 3. Organize GoPro Data (per-session structure)

**Why needed**: Raw data is per-camera structure, pipeline requires per-session structure.

**How it works**:
- Scans all MP4 files under each `cam*/` directory
- Sorts by filename number (GoPro auto-incrementing numbers = recording time order)
- Assumes the **Nth video from each camera = Nth session**
- `--participant P7` sets the output directory name prefix (P7_1, P7_2, ...)
- Also copies `qr_sync.mp4` to the output directory root

**Prerequisite**: All GoPros start/stop recording simultaneously for each session, ensuring filename number correspondence is correct.

```bash
# Preview (dry-run)
python workflow/organize_gopro_videos.py \
    --input /Volumes/FastACIS/csl_11_5/P7_gopro \
    --output /Volumes/FastACIS/csl_11_5/organized \
    --participant P7 \
    --dry-run

# Execute after confirmation
python workflow/organize_gopro_videos.py \
    --input /Volumes/FastACIS/csl_11_5/P7_gopro \
    --output /Volumes/FastACIS/csl_11_5/organized \
    --participant P7
```

**Output Structure**:
```
organized/
├── qr_sync.mp4           # Copied QR anchor video
├── P7_1/
│   ├── cam1/GX010279.MP4
│   ├── cam2/GX010276.MP4
│   └── ... (16 cameras)
├── P7_2/, P7_3/, P7_4/, P7_5/
```

---

## Pipeline Overview

### Dependency Flow Diagram

```
Data Preparation
├── Place Mocap raw data (AVI + CSV + .mcal)
└── Organize GoPro raw data (per-camera → per-session)
    ↓
Phase 1: Mocap Data Processing (automatic)
├── Output: video.mp4, skeleton_h36m.npy, body_markers.npy, blade_editor_*.html
└── ⚠️ Manual: Open HTML editor, annotate blade edges → blade_polygon_order_*.json
    ↓
Phase 2: Blade Edge Extraction + cam19 Refinement
├── Output: *_edges.npy (blade 3D trajectories)
└── ⚠️ Manual: Run refine_extrinsics.py to optimize cam19 → cam19_refined.yaml
    ↓
Phase 3: GoPro Complete Pipeline (automatic)
├── 3.1 GoPro QR sync
├── 3.2 PrimeColor sync
├── 3.3 17-camera joint calibration (calibration session only)
├── 3.4 Generate per-camera YAMLs
└── 3.5 GT distribution → cam*/gt/skeleton.npy, blade_edges.npy, valid_mask.npy
    ↓
Verification (optional, manual)
├── verify_gt_offset.py → Check temporal alignment
├── verify_cam19_gt.py → Visualize projection quality
└── refine_extrinsics.py → Individually refine a GoPro (if needed)
    ↓
Done: cam*/gt/ ready for training
```

---

## Three Pipeline Phases

### Phase 1: Mocap Data Processing

**Purpose**: Merge AVI videos + CSV to GT + Generate blade annotation tools

#### Input

| File | Source | Description |
|------|--------|-------------|
| `P7_X/*.avi` | Motive recording | PrimeColor 120fps video (may have multiple segments) |
| `P7_X/*.csv` | Motive export | Skeleton + marker 3D coordinates |
| `*.mcal` | OptiTrack calibration | Contains cam19 initial intrinsics and extrinsics |

#### Command

```bash
# Batch process all sessions
python workflow/process_mocap_session.py \
    /Volumes/KINGSTON/P7_mocap \
    -o /Volumes/KINGSTON/P7_output \
    --batch
```

#### Output (per session)

| File | Shape / Format | Description |
|------|---------------|-------------|
| `video.mp4` | 120fps, 1920x1080 | PrimeColor video (multi-segment merged, watermark removed) |
| `cam19_initial.yaml` | YAML (K, D, R, t) | Initial intrinsics and extrinsics extracted from .mcal |
| `skeleton_h36m.npy` | `(N, 17, 3)` | H36M format skeleton, 17 joints, world coordinates |
| `body_markers.npy` | `(N, 27, 3)` | Plug-in Gait markers (used for cam19 refinement) |
| `leg_markers.npy` | `(N, 8, 3)` | Amputee-side markers L1-L4, R1-R4 |
| `blade_editor_*.html` | HTML | Interactive 3D blade annotation tool |

```
P7_output/P7_1/
├── video.mp4
├── cam19_initial.yaml
├── skeleton_h36m.npy
├── body_markers.npy, body_marker_names.json
├── leg_markers.npy, leg_marker_names.json
├── blade_editor_Rblade.html
├── blade_editor_lblade2.html
└── ...
```

#### 🔧 Interactive Step: Blade Edge Annotation

**Must be completed manually** (annotate each blade once, shared across all sessions)

1. **Open HTML editor**:
   ```bash
   open /Volumes/KINGSTON/P7_output/P7_1/blade_editor_Rblade.html
   ```

2. **Annotate edge order**:
   - Select **Edge 1**, click blade first edge markers in order (tip→root or reverse)
   - Switch to **Edge 2**, click blade second edge markers in **same direction**
   - Ensure both edges have consistent direction (both tip→base or both base→tip)

3. **Export JSON**:
   - Click **Export JSON**
   - Save as `blade_polygon_order_Rblade.json`
   - Place in `/Volumes/KINGSTON/P7_output/P7_1/` directory

4. **Repeat for other blades**:
   - If lblade2 exists, repeat above steps to generate `blade_polygon_order_lblade2.json`

**Keyboard Shortcuts**:
- `1` / `2`: Switch Edge 1/2
- `Z`: Undo
- `R`: Reset view
- Left drag: Rotate, Right drag: Pan, Scroll: Zoom

---

### Phase 2: Blade Edge Extraction + cam19 Refinement

**Purpose**: Extract blade 3D trajectories from CSV + Optimize cam19 extrinsics

#### Input (Dependencies)

| File | Source | Description |
|------|--------|-------------|
| `P7_X/*.csv` | Mocap raw data | Contains blade rigid body marker coordinates |
| `blade_polygon_order_*.json` | **Phase 1 manual annotation** | Defines marker order for blade two edges |
| `body_markers.npy` | Phase 1 output | Marker correspondences for cam19 refinement |
| `video.mp4` | Phase 1 output | Video for cam19 refinement |
| `cam19_initial.yaml` | Phase 1 output | cam19 initial parameters (refinement starting point) |

#### Command

```bash
# Share P7_1 JSON to other sessions, then batch extract
python workflow/process_blade_session.py \
    /Volumes/KINGSTON/P7_mocap \
    -o /Volumes/KINGSTON/P7_output \
    --batch \
    --share_json P7_1
```

#### Output (per session)

| File | Shape | Description |
|------|-------|-------------|
| `Rblade_edge1.npy` | `(N, M, 3)` | Edge 1 raw marker trajectory |
| `Rblade_edge2.npy` | `(N, M, 3)` | Edge 2 raw marker trajectory |
| `Rblade_edges.npy` | `(N, K, 2, 3)` | Arc-length resampled edge pairs |
| `Rblade_marker_names.json` | JSON | Rigid body name and marker grouping |

> Same pattern for `lblade2_*` files, if a second blade exists.

**Key**: In the `*_edges.npy` shape, `K` = maximum marker count across the two edges (uniformly spaced after arc-length resampling), `2` = the two edges, `3` = xyz world coordinates

#### 🔧 Interactive Step: cam19 Extrinsics Optimization

**Purpose**: Optimize PrimeColor camera extrinsics (intrinsics + extrinsics) for precise mocap marker projection alignment

**Session Selection**: Choose session with **largest motion range** (e.g., P7_4), optimize once and apply to all sessions

```bash
# cam19 direct mode (explicit paths, since files are in P7_output not synced dir)
python post_calibration/refine_extrinsics.py \
    --markers /Volumes/KINGSTON/P7_output/P7_4/body_markers.npy \
    --video /Volumes/KINGSTON/P7_output/P7_4/video.mp4 \
    --camera /Volumes/KINGSTON/P7_output/P7_4/cam19_initial.yaml \
    --output /Volumes/KINGSTON/P7_output/P7_4/cam19_refined.yaml
```

**Operation Steps**:
1. **Find clear frame**: Press `f` to auto-find frames with clear and stable markers
2. **Annotate marker pairs**:
   - Left click 3D marker (left list)
   - Right click corresponding true position in video
   - Repeat for at least **6 marker pairs** (8-10 recommended)
3. **Optimize parameters**:
   - Press `O`: Use scipy optimization (14 params: intrinsics fx,fy,cx,cy + distortion k1-k6 + extrinsics rvec,tvec)
   - Press `P`: Use solvePnP (extrinsics only, requires 4+ pairs)
4. **Verify projection**:
   - Use `[` / `]` to switch frames, check if projection stays aligned
   - If error is large, add more marker pairs or re-optimize
5. **Export**: Press `e` to save `cam19_refined.yaml`

**Keyboard Shortcuts Summary**:
- `f`: Auto-find stable frame
- `Space`: Play/pause
- `[` / `]`: Previous/next frame
- `,` / `.`: Previous/next 10 frames
- `O`: scipy optimization (recommended)
- `P`: solvePnP optimization
- `u`: Undo last marker pair
- `c`: Clear all pairs
- `e`: Export YAML
- `q`: Quit

**Target**: Reprojection error < 2.0 pixels (ideal < 1.5 pixels)

---

### Phase 3: GoPro Complete Pipeline

**Purpose**: GoPro sync + PrimeColor sync + 17-camera joint calibration + YAML generation + GT distribution

#### Input (Dependencies)

| File | Source | Description |
|------|--------|-------------|
| `organized/P7_X/cam*/*.MP4` | Data Preparation step 3 | Per-session organized GoPro videos |
| `organized/qr_sync.mp4` | Data Preparation step 3 | QR anchor video |
| `cam19_refined.yaml` | **Phase 2 manual optimization** | Participant-level cam19 optimized parameters |
| `skeleton_h36m.npy` | Phase 1 output | For GT distribution |
| `*_edges.npy` | Phase 2 output | For GT distribution (blade trajectories) |

#### Command

```bash
python workflow/process_p7_complete.py \
    --organized_dir /Volumes/FastACIS/csl_11_5/organized \
    --mocap_dir /Volumes/KINGSTON/P7_output \
    --output_dir /Volumes/FastACIS/csl_11_5/synced \
    --anchor_video /Volumes/FastACIS/csl_11_5/organized/qr_sync.mp4 \
    --calibration_session P7_1 \
    --start_time 707 \
    --duration 264 \
    --sessions P7_1 P7_2 P7_3 P7_4 P7_5
```

**Note**:
- `--cam19_refined` parameter is optional (auto-searches `P7_output/*/cam19_refined.yaml`)

#### How to Determine `--calibration_session` and `--start_time` / `--duration`

Calibration requires the ChArUco board to be **stable and clearly visible** in the frame. To determine these values:

1. **Choose calibration session**: Open any GoPro video from each session (raw pre-sync video is fine) and find the session where the ChArUco board appears and remains stationary for a long period. This is typically when the board is placed at the start or end of recording
2. **Determine start_time**: Find the approximate second when the board starts being stationary. Use a video player to scrub the timeline
3. **Determine duration**: The length of time (in seconds) the board stays still. At least 60 seconds is recommended; longer is better (more stable frames = lower RMS)
4. **Verify**: The pipeline saves detected stable frames in `original_stable/`. If fewer than 100 stable frames are found, consider expanding the time range or switching sessions

**Example**: If the ChArUco board is stationary between seconds 707 and 971 in P7_1's GoPro video, then use `--start_time 707 --duration 264`

#### Pipeline Automatic Execution Steps

**Phase 3.1: GoPro QR Sync** (~5 min/session)
- Time-synchronize all 16 GoPros using QR anchor video
- Output: `P7_X_sync/cameras_synced/cam1-18/*.MP4` (synced, 60fps)
- Skip logic: Skip if `meta_info.json` exists

**Phase 3.2: PrimeColor Sync** (~2 min/session)
- Resample PrimeColor 120fps video to 60fps based on GoPro timeline
- Output:
  - `cam19/primecolor_synced.mp4` (60fps)
  - `cam19/sync_mapping.json` (temporal mapping)
- Skip logic: Skip if output files exist

**Phase 3.3: 17-Camera Joint Calibration** (~15 min, calibration_session only)
- Extract frames (5 fps, specified time range)
- Detect ChArUco board stable frames
- Run `multical` joint optimization, generate `calibration.json`
- **Target RMS**: < 1.6 pixels (excellent), < 2.5 pixels (acceptable)
- Skip logic: Skip if `calibration.json` exists

**Phase 3.4: Generate Individual YAMLs** (~1 min)
- Combine:
  - `calibration.json` (GoPro inter-camera extrinsics, shared across all sessions)
  - `cam19_refined.yaml` (Mocap → cam19, participant-wide)
- Generate 17 camera YAMLs: `cam1.yaml`, ..., `cam18.yaml`, `cam19.yaml`
- Output location: `individual_cam_params/`

**Phase 3.5: GT Distribution** (~1 min/session)
- Create symlinks to the cam19/ directory:
  - `skeleton_h36m.npy` → mocap output skeleton data
  - `Rblade_edges.npy`, `lblade2_edges.npy` → per-blade edge data
  - `aligned_edges.npy` → **primary blade symlink** (priority: Rblade > lblade2 > first blade found)
- `aligned_edges.npy` explanation: This is a convenience symlink that `distribute_gt.py` reads to produce each camera's `blade_edges.npy`. For bilateral amputees (with both Rblade and lblade2), **only the primary blade is distributed as the generic `blade_edges.npy`**. Each blade's original file is still accessible individually through the named symlinks in cam19/
- Call `distribute_gt.py` to resample 120fps mocap data to each GoPro 60fps timeline
- Output: `cam*/gt/skeleton.npy`, `cam*/gt/blade_edges.npy`, `cam*/gt/valid_mask.npy`

---

## Verification and Optimization Tools

### 1. GT Temporal Alignment Verification

**Purpose**: Check if skeleton projection aligns precisely with video frames (temporal sync correctness)

```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /Volumes/FastACIS/csl_11_5/synced/P7_1_sync/cameras_synced \
    --camera cam1 \
    --start 60 \
    --duration 10
```

**Operations**:
- `Space`: Play/replay
- `[` / `]`: Adjust offset ±1 frame
- `,` / `.`: Adjust offset ±0.5 frame
- `e`: Save offset to `camera_offsets.json` and auto-redistribute GT
- `q`: Quit

**Target**: Skeleton joints always overlay on athlete's body, no noticeable delay or advance

---

### 2. cam19 Visualization Verification

**Purpose**: Verify cam19 refinement effect, view skeleton + blade edges projection quality

```bash
python post_calibration/verify_cam19_gt.py \
    --video /Volumes/KINGSTON/P7_output/P7_1/video.mp4 \
    --camera_yaml /Volumes/KINGSTON/P7_output/P7_4/cam19_refined.yaml \
    --gt_dir /Volumes/KINGSTON/P7_output/P7_1/ \
    --start 30 \
    --duration 10 \
    --scale 0.5 \
    --output cam19_P7_1_vis.mp4
```

**Output**: Video with skeleton + blade projection overlay (auto-detects all blades)

**Features**:
- Auto-detects `Rblade_edges.npy`, `lblade2_edges.npy`, etc.
- Different blades use different colors
- 120fps original video, full framerate output

---

### 3. Individual GoPro Extrinsics Optimization (Optional)

**Purpose**: If a specific GoPro has poor projection quality, optimize its extrinsics individually

```bash
# Convenience mode: just session + cam + two base paths
python post_calibration/refine_extrinsics.py \
    --session P7_1 --cam cam3 \
    --markers-base /Volumes/KINGSTON/P7_output \
    --synced-base /Volumes/FastACIS/csl_11_5/synced
```

**Operation steps same as cam19 refinement**

---

## Output Directory Structure

### Mocap Output

```
/Volumes/KINGSTON/P7_output/
├── P7_1/
│   ├── video.mp4                      # 120fps PrimeColor
│   ├── cam19_initial.yaml
│   ├── skeleton_h36m.npy
│   ├── body_markers.npy
│   ├── leg_markers.npy
│   ├── Rblade_edges.npy               # (N, K, 2, 3)
│   ├── lblade2_edges.npy
│   └── blade_polygon_order_*.json
├── P7_2/, P7_3/, P7_4/, P7_5/
└── P7_4/
    └── cam19_refined.yaml             # Refined cam19 (applied to all sessions)
```

### GoPro + Calibration Output

```
/Volumes/FastACIS/csl_11_5/
├── organized/                         # Phase 0: Organized raw data
│   ├── qr_sync.mp4
│   └── P7_X/cam*/video.MP4
└── synced/
    └── P7_X_sync/cameras_synced/
        ├── meta_info.json             # GoPro sync metadata
        ├── cam1/, ..., cam18/         # Synced GoPro videos
        ├── cam19/
        │   ├── primecolor_synced.mp4  # 60fps
        │   ├── sync_mapping.json
        │   ├── skeleton_h36m.npy      # Symlink
        │   ├── Rblade_edges.npy       # Symlink
        │   ├── lblade2_edges.npy      # Symlink
        │   └── aligned_edges.npy      # Symlink → Primary blade
        ├── original/                  # Extracted frames (for calibration)
        ├── original_stable/           # Stable frames
        │   └── calibration.json       # Only in calibration_session (P7_1)
        ├── individual_cam_params/     # Per-camera YAMLs
        │   ├── cam1.yaml
        │   ├── ...
        │   └── cam19.yaml
        ├── camera_offsets.json        # Per-camera temporal offset (optional)
        └── cam*/gt/                   # Distributed GT data
            ├── skeleton.npy           # (N_gopro, 17, 3)
            ├── blade_edges.npy        # (N_gopro, K, 2, 3)
            ├── valid_mask.npy         # (N_gopro,) bool
            └── gt_info.json
```

---

## Troubleshooting

### 1. pyzbar Warning

**Issue**: `⚠️ Recommend installing pyzbar acceleration`

**Solution**:
```bash
pip install pyzbar
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"
```

### 2. High RMS Error

**Issue**: `calibration.json` RMS > 2.5 pixels

**Causes**:
- Poor ChArUco board detection quality
- Insufficient stable frames (< 100 frames)
- Selected time range has fast board movement

**Solutions**:
1. Re-select time range (`--start_time` / `--duration`), ensure board is stable for long period
2. Check frame count in `original_stable/`
3. Lower `find_stable_boards.py` `--movement_threshold` (default 5.0)

### 3. GT Temporal Misalignment

**Issue**: Skeleton projection misaligned, delayed or advanced

**Solution**:
```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /path/to/cameras_synced \
    --camera camX
```
Adjust offset then press `e` to save and redistribute GT

### 4. cam19 Refinement Failure

**Issue**: Projection error remains large

**Causes**:
- body_markers.npy doesn't exist (missing in some sessions)
- Selected frame has unclear or occluded markers
- Too few annotated marker pairs (< 6)

**Solutions**:
1. Ensure `body_markers.npy` exists
2. Press `f` multiple times to find different clear frames
3. Annotate 8-10 clear marker pairs
4. Use `O` (scipy) instead of `P` (solvePnP)

### 5. cam19_refined.yaml Not Found

**Issue**: `process_p7_complete.py` reports cam19_refined.yaml not found

**Cause**: Phase 2 not run or refinement not exported

**Solutions**:
1. Verify at least one session under `/Volumes/KINGSTON/P7_output/` contains `cam19_refined.yaml`
2. If not, run Phase 2 interactive refinement step
3. Manually specify path: `--cam19_refined /path/to/cam19_refined.yaml`

---

## Complete Time Estimation

| Phase | Time | Notes |
|-------|------|-------|
| **Data Preparation** | | |
| Organize GoPro videos | ~5 min | File copy/move |
| **Phase 1: Mocap Processing** | | |
| AVI→MP4 + CSV→GT | ~30 min | 5 sessions serial |
| Blade HTML annotation | ~10 min | Once per blade (manual) |
| **Phase 2: Blade Extract + cam19 Refine** | | |
| Blade edges extraction | ~5 min | Batch automatic |
| cam19 refinement | ~10 min | Once (manual) |
| **Phase 3: GoPro Pipeline** | | |
| GoPro QR sync | ~25 min | 5 sessions × 5 min |
| PrimeColor sync | ~10 min | 5 sessions × 2 min |
| Calibration (P7_1) | ~15 min | Once |
| Generate YAMLs | ~5 min | All sessions |
| Distribute GT | ~5 min | All sessions |
| **Total** | **~2 hours** | Including interactive time |

---

## Next Steps

After completing the pipeline:

1. ✅ **Verify projection quality**: Use `verify_gt_offset.py` to check temporal alignment for each camera
2. ✅ **Visual inspection**: Use `verify_cam19_gt.py` to view skeleton + blade projection effect
3. ✅ **Start training/inference**: Use data in `cam*/gt/` for model training

Good luck! 🚀
