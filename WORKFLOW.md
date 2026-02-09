# CSL 17-Camera Calibration Pipeline

Complete workflow for synchronizing and calibrating 17 cameras (16 GoPro + 1 PrimeColor cam19) from raw organized data to per-camera extrinsic YAML files, and distributing ground truth data to each camera.

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Data Organization](#2-data-organization)
3. [Prerequisites](#3-prerequisites)
4. [Phase 0: GT Data Generation](#4-phase-0-gt-data-generation)
5. [Phase A: One-time Pipeline (P4_1)](#5-phase-a-one-time-pipeline-p4_1)
6. [Phase B: Per-session Pipeline](#6-phase-b-per-session-pipeline)
7. [Script Reference](#7-script-reference)
8. [Configuration Reference](#8-configuration-reference)
9. [Data Format Specifications](#9-data-format-specifications)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. System Overview

### Hardware Setup

| Component | Count | Spec | FPS | Resolution |
|-----------|-------|------|-----|------------|
| GoPro Hero | 16 (cam1-cam12, cam15-cam18) | HyperSmooth OFF, Linear lens | 60fps | 3840x2160 (4K) |
| PrimeColor (cam19) | 1 | OptiTrack camera | 120fps source, 60fps synced | 1920x1080 |
| OptiTrack Mocap | - | Motion capture markers | 120fps | - |

Notes:
- cam13 and cam14 are not used in this setup
- GoPro cameras are mounted on a fixed rig (relative positions do not change between sessions)
- PrimeColor cam19 is OptiTrack-calibrated, its Mocap-to-camera transform varies per session
- All GoPros are synced via QR anchor video; PrimeColor is synced separately to the GoPro timeline

### Architecture: Two-Phase Design

The pipeline exploits the fact that the GoPro camera rig is fixed:

- **Phase A (one-time, on P4_1)**: Full pipeline, joint 17-camera calibration produces `calibration.json` with all camera-to-camera relative transforms
- **Phase B (per-session)**: Only cam19's Mocap-to-camera transform changes. Refine cam19, then combine with the shared `calibration.json` to regenerate per-camera YAML files

The transform chain is: **Mocap -> cam19 -> cam1 (base) -> camX**

### Recording Sessions

**P4-P6 (15 sessions)**: Original dataset organized as `{session}/` on T7 drive:
```
P4: P4_1, P4_2, P4_3, P4_4, P4_5
P5: P5_1, P5_2, P5_3, P5_4, P5_5
P6: P6_1, P6_2, P6_3, P6_4, P6_5
```

**P7+ (new format)**: Data organized as `Px_mocap/` and `Px_gopro/`:
```
P7: P7_1, P7_2, P7_3, P7_4, P7_5   (bilateral amputation, stored on KINGSTON)
```
P7+ raw mocap data lives in `Px_mocap/P7_N/` containing Motive CSV + AVI video segments.
Use `workflow/process_mocap_session.py` to process into pipeline-ready format (see Phase 0b).

---

## 2. Data Organization

### Input Data (Two Source Locations)

**Source 1: GoPro videos (organized)**
```
/Volumes/FastACIS/csl_11_5/organized/
├── qr_sync.mp4                          # QR anchor video (reference for all GoPro sync)
├── P4_1/
│   ├── cam1/P4_1.MP4                    # GoPro video (uppercase .MP4)
│   ├── cam2/P4_2.MP4
│   ├── ...
│   └── cam18/P4_1.MP4
├── P4_2/
│   └── ...
└── P6_5/
    └── ...
```

**Source 2: PrimeColor + Mocap + GT data**
```
/Volumes/T7/csl/
├── Cal 2026-02-01 14.15.20 Exported.mcal  # OptiTrack calibration (XML, UTF-16-LE)
├── P4_1/
│   ├── primecolor.mp4                      # PrimeColor video (lowercase .mp4, 120fps)
│   ├── body_markers.npy                    # Mocap marker positions (120fps, Nx3)
│   ├── body_marker_names.json              # Marker name mapping
│   ├── skeleton_h36m.npy                   # 3D skeleton GT (120fps, N x 17 x 3)
│   ├── blade_edges.npy                     # Blade edge GT (120fps, N x E x 2 x 3)
│   ├── blade_edge1.npy                     # Blade edge endpoint 1 (120fps)
│   └── blade_edge2.npy                     # Blade edge endpoint 2 (120fps)
├── P5_1/
│   ├── skeleton_h36m.npy                   # Has GT but no body_markers.npy
│   ├── blade_edges.npy
│   └── ...                                 # (cam19 refinement requires body_markers.npy)
├── P5_4/
│   ├── skeleton_h36m.npy                   # Has GT but no body_markers.npy (only CSV)
│   ├── blade_edges.npy
│   └── *.csv                               # Some sessions have CSV instead of npy
└── P6_5/
    └── ...
```

Note: All 15 sessions (P4_1-P6_5) have `skeleton_h36m.npy` and `blade_edges.npy`. The `body_markers.npy` (needed for cam19 refinement) is missing in P5_1 and P5_4.

**Source 3: P7+ Raw Mocap (new format)**
```
/Volumes/KINGSTON/P7_mocap/
├── P7_1/
│   ├── session1.csv                           # Motive 1.25 CSV export (120fps)
│   ├── session1-Camera 13 (C13013).avi        # PrimeColor AVI segment 1 (MJPEG 1920x1080 120fps)
│   ├── session1-Camera 13 (C13013) (1).avi    # PrimeColor AVI segment 2
│   └── session1-Camera 13 (C13013) (2).avi    # PrimeColor AVI segment 3...
├── P7_2/
│   └── ...
└── P7_5/
    └── ...
```

Notes:
- Motive splits recordings into ~3.7GB AVI segments (AVI file size limit)
- AVI segment ordering: base file (no number) = 1st, then (1), (2), (3)...
- AVI codec: MJPEG 1920x1080 120fps, bottom-left has a frame counter watermark
- P7 has bilateral amputation: L1/L2/R1/R2 (knee markers) exist, but NO L3/L4/R3/R4 (ankle markers)
- Only P7_1 had correct L1/L2/R1/R2 marker naming; P7_2-P7_5 used generic numbering (fixed via `scripts/fix_leg_marker_names.py`)

IMPORTANT: FastACIS volume uses **Case-sensitive APFS**. `*.MP4` (GoPro) and `*.mp4` (PrimeColor) are different files.

### Output Data (After Pipeline)

```
/Volumes/FastACIS/csl_11_5/synced/
├── P4_1_sync/
│   └── cameras_synced/
│       ├── meta_info.json                  # GoPro sync metadata (offsets, durations)
│       ├── cam1/
│       │   ├── P4_1.MP4                    # Synced GoPro video (trimmed to common window)
│       │   └── gt/                         # Distributed GT data (after Step A8)
│       │       ├── skeleton.npy            #   (N_gopro, 17, 3) float32
│       │       ├── blade_edges.npy         #   (N_gopro, E, 2, 3) float32
│       │       ├── valid_mask.npy          #   (N_gopro,) bool
│       │       └── gt_info.json            #   metadata
│       ├── cam2/, ..., cam18/              # Same structure as cam1/
│       ├── cam19/
│       │   ├── primecolor_synced.mp4       # Synced PrimeColor video (60fps, resampled)
│       │   ├── sync_mapping.json           # PrimeColor frame-to-GoPro frame mapping
│       │   ├── skeleton_h36m.npy -> /Volumes/T7/csl/P4_1/skeleton_h36m.npy  # symlink
│       │   └── aligned_edges.npy -> /Volumes/T7/csl/P4_1/blade_edges.npy    # symlink (renamed)
│       ├── cam19_initial.yaml              # Initial cam19 extrinsics (from mcal)
│       ├── cam19_refined.yaml              # Refined cam19 extrinsics (after interactive tool)
│       ├── camera_offsets.json             # Per-camera frame offsets (optional, default 0)
│       ├── original/                       # Extracted frames (all 17 cameras)
│       │   ├── cam1/frame_0001.jpg, ...
│       │   ├── ...
│       │   └── cam19/frame_0001.jpg, ...
│       ├── original_stable/                # Subset: stable ChArUco frames (union)
│       │   ├── cam1/frame_0042.jpg, ...
│       │   ├── ...
│       │   ├── cam19/frame_0042.jpg, ...
│       │   └── calibration.json            # Joint 17-camera extrinsic calibration
│       ├── stable_frames_detection.json    # Per-camera stable frame indices
│       └── individual_cam_params/          # Final per-camera YAML files
│           ├── cam1.yaml                   # Mocap -> cam1 transform
│           ├── cam2.yaml                   # Mocap -> cam2 transform
│           ├── ...
│           └── cam19.yaml                  # Mocap -> cam19 transform (= cam19_refined)
├── P4_2_sync/
│   └── cameras_synced/
│       ├── ... (synced videos, same structure)
│       ├── cam19_refined.yaml              # Session-specific cam19
│       ├── individual_cam_params/          # Uses shared calibration.json + this cam19
│       └── cam*/gt/                        # GT distributed per camera
└── ...
```

---

## 3. Prerequisites

### Environment

```bash
conda activate multical
```

Required packages: numpy==1.23, opencv-python==4.6.0.66, opencv-contrib-python==4.6.0.66, scipy, pyzbar, ffmpeg (conda-forge)

### Key Files in csl_pipeline/

| File | Purpose |
|------|---------|
| `camera_config.sh` | Defines camera lists and session names |
| `intrinsic_all_17_cameras.json` | Merged intrinsics for all 17 cameras |
| `intrinsic_hyperoff_linear_60fps.json` | GoPro-only pre-calibrated intrinsics |
| `multical/asset/charuco_b1_2.yaml` | ChArUco board definition (B1 size, 10x14 grid) |

### Verify Volumes

Before running any pipeline step:

```bash
ls /Volumes/FastACIS/csl_11_5/organized/    # GoPro source
ls /Volumes/T7/csl/                          # PrimeColor + Mocap source
ls /Volumes/FastACIS/csl_11_5/synced/        # Output directory
```

---

## 4. Phase 0: GT Data Generation

Phase 0 generates ground truth (GT) data from raw OptiTrack Motive CSV exports. This is a prerequisite for cam19 refinement (Phase A Step A3) and GT distribution (Phase A Step A8).

### Overview

Three types of GT data are generated from each session's Motive CSV:

| Output | Shape | Description | Script |
|--------|-------|-------------|--------|
| `skeleton_h36m.npy` | (N, 17, 3) float64 | H36M 17-joint skeleton, mm, Y-up | `csv2h36m.py` |
| `blade_edges.npy` | (N, E, 2, 3) float32 | Blade ruled surface edges, arc-length resampled | `extract_blade_edges.py` |
| `body_markers.npy` | (N, 27, 3) float32 | 27 Plug-in Gait body markers | `extract_markers.py` |

N = number of mocap frames (120fps). E = number of resampled edge points (typically 10).

### H36M Skeleton Generation Chain

```
Motive CSV (120fps, Bone + Marker data)
    ↓  csv2h36m.py
    ↓  Auto-detects skeleton prefix: body | Skeleton 001 | P2 | P3
    ↓  Auto-detects amputation side: right_leg | left_leg
    ↓  Multi-pass marker preprocessing (nearest-frame offset filling + interpolation)
    ↓
    ├── Joint 0 (Hip): mean(LASI, RASI, LPSI, RPSI) markers
    ├── Joint 1 (RHip): mean(RASI, RPSI)
    ├── Joint 2 (RKnee): mean(R1, R2) leg markerset
    ├── Joint 3 (RAnkle): mean(R3, R4) OR NaN if amputated
    ├── Joint 4 (LHip): mean(LASI, LPSI)
    ├── Joint 5 (LKnee): mean(L1, L2) leg markerset
    ├── Joint 6 (LAnkle): mean(L3, L4) OR NaN if amputated
    ├── Joint 7 (Spine): Chest bone position
    ├── Joint 8 (Thorax): Neck bone position
    ├── Joint 9 (Nose): Head bone pos + forward quat × 100mm
    ├── Joint 10 (Head): mean(LFHD, RFHD, LBHD, RBHD) markers
    ├── Joint 11 (LShoulder): LUArm bone position
    ├── Joint 12-13 (LElbow, LWrist): LFArm, LHand bone positions
    └── Joint 14-16 (RShoulder, RElbow, RWrist): RUArm, RFArm, RHand bone positions
→ Hybrid approach: Motive bone positions (arms/spine) + raw marker means (pelvis/head/knees/ankles)
```

Amputation side varies per participant:
- **Right leg** (P4, P5_3, P6): LAnkle (Joint 6) = NaN, RAnkle from R3+R4
- **Left leg** (P5_2, P5_4, P5_5): RAnkle (Joint 3) = NaN, LAnkle from L3+L4
- **Bilateral** (P7): Both ankles = NaN, has L1/L2/R1/R2 but no L3/L4/R3/R4

### Blade Edge Extraction Chain

```
Motive CSV (Rigid Body Marker data for "Blade")
    ↓  Manual: polygon_editor.html → blade_polygon_order.json
    ↓       (defines edge1 + edge2 marker ordering along blade)
    ↓  extract_blade_edges.py
    ↓  Arc-length resampling to uniform spacing
    ↓
    ├── blade_edge1.npy: (N, M1, 3) raw edge 1 positions
    ├── blade_edge2.npy: (N, M2, 3) raw edge 2 positions
    └── blade_edges.npy: (N, E, 2, 3) aligned pairs (E=max(M1,M2))
```

Ruled surface: `S(s,u) = (1-u) * edge1[s] + u * edge2[s]`

### Body Marker Extraction Chain

```
Motive CSV → extract_markers.py → body_markers.npy (N, 27, 3)
27 Plug-in Gait markers: C7, CLAV, LASI, LBHD, LELB, LFHD, LFIN, LFRM,
  LPSI, LSHO, LUPA, LWRA, LWRB, RASI, RBAK, RBHD, RELB, RFHD, RFIN,
  RFRM, RPSI, RSHO, RUPA, RWRA, RWRB, STRN, T10
```

### Quick Run (All Sessions)

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# Generate all 3 GT types for all sessions (skips P5_1 auto)
./run_generate_gt.sh

# Or specific steps/sessions:
./run_generate_gt.sh --step skeleton --only P4_1,P4_2
./run_generate_gt.sh --step markers
./run_generate_gt.sh --dry-run  # preview commands
```

### Step-by-Step

#### 0.1: Generate skeleton_h36m.npy

```bash
# Single session
python scripts/csv2h36m.py /Volumes/T7/csl/P4_1/Take*.csv \
    -o /Volumes/T7/csl/P4_1/skeleton_h36m.npy

# Batch (all sessions except P5_1)
python scripts/batch_csv2h36m.py --base /Volumes/T7/csl

# P5_1 special case (no L/R naming, requires manual --amputation flag):
python scripts/csv2h36m.py /Volumes/T7/csl/P5_1/Take*.csv \
    --amputation right_leg \
    -o /Volumes/T7/csl/P5_1/skeleton_h36m.npy
```

#### 0.2: Generate blade_edges.npy

Prerequisite: `blade_polygon_order.json` must exist in each session's directory (created manually using polygon_editor.html).

```bash
# Batch (extracts for all sessions that have blade_polygon_order.json)
python scripts/batch_extract_blade_edges.py --base /Volumes/T7/csl

# Single session (using csv_structures.json)
python scripts/extract_blade_edges.py --base /Volumes/T7/csl --dataset P4_1

# Single session (direct CSV)
python scripts/extract_blade_edges.py \
    --csv /Volumes/T7/csl/P4_1/Take*.csv \
    --rigid-body Blade \
    --json /Volumes/T7/csl/P4_1/blade_polygon_order.json \
    -o /Volumes/T7/csl/P4_1/
```

#### 0.3: Generate body_markers.npy

```bash
# Batch (all sessions except P5_1)
python scripts/batch_extract_markers.py --base /Volumes/T7/csl --legs

# Single session
python scripts/extract_markers.py /Volumes/T7/csl/P4_1/Take*.csv \
    -o /Volumes/T7/csl/P4_1/ --legs
```

### Prerequisites for Phase 0

| Prerequisite | Location | Notes |
|-------------|----------|-------|
| `csv_structures.json` | `/Volumes/T7/csl/` | Pre-analyzed CSV metadata (run `batch_analyze_csv.py` if missing) |
| `blade_polygon_order.json` | `/Volumes/T7/csl/{SESSION}/` | Manual edge definition (one-time per session) |
| Motive CSV exports | `/Volumes/T7/csl/{SESSION}/Take*.csv` | Raw OptiTrack data |

### Known Issues

| Session | Issue | Workaround |
|---------|-------|------------|
| P5_1 | No L/R marker naming, auto-detection fails | Use `--amputation right_leg` flag manually |
| P5_4 | Only segment CSVs (no single merged CSV) | `extract_blade_edges.py` handles segments; `csv2h36m.py` needs merged CSV |
| P5_1, P5_4 | No `body_markers.npy` generated | cam19 refinement blocked for these sessions |

---

## 4b. Phase 0b: One-Command Session Processing (P7+)

For P7+ data (stored as `Px_mocap/`), use the unified `process_mocap_session.py` workflow tool that generates all GT data in a single command.

### What It Does (4 Steps)

1. **AVI → MP4**: Finds AVI segments, concatenates in correct order, removes bottom-left watermark, outputs `primecolor.mp4`
2. **CSV → Skeleton**: Generates `skeleton_h36m.npy` (17 H36M joints) with auto-detected amputation mode (right/left/bilateral)
3. **CSV → Markers**: Generates `body_markers.npy` (27 Plug-in Gait) + `leg_markers.npy` (L1/L2/R1/R2)
4. **Blade Editor HTML**: Generates interactive `blade_editor_*.html` for each blade rigid body found in the CSV

### Usage

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# Process single session
python workflow/process_mocap_session.py \
    /Volumes/KINGSTON/P7_mocap/P7_1 \
    -o /Volumes/FastACIS/csl_output/P7_1

# Process all sessions under a directory
python workflow/process_mocap_session.py \
    /Volumes/KINGSTON/P7_mocap \
    -o /Volumes/FastACIS/csl_output \
    --batch

# Skip video processing (CSV + blade only)
python workflow/process_mocap_session.py \
    /Volumes/KINGSTON/P7_mocap/P7_1 \
    -o /Volumes/FastACIS/csl_output/P7_1 \
    --no_video
```

### Output Structure

```
output_dir/
├── primecolor.mp4              # Concatenated + cleaned video (120fps, 1920x1080)
├── skeleton_h36m.npy           # (N, 17, 3) float64 — H36M joints, Y-up, mm
├── body_markers.npy            # (N, 27, 3) float32 — 27 Plug-in Gait markers
├── body_marker_names.json      # Ordered marker name list
├── leg_markers.npy             # (N, M, 3) float32 — Leg markers (L1/L2/R1/R2)
├── leg_marker_names.json       # Ordered leg marker name list
├── blade_editor_Rblade.html    # Interactive blade polygon editor (Plotly.js)
└── blade_editor_lblade2.html   # One HTML per blade rigid body
```

### Amputation Detection

The tool auto-detects amputation mode from the CSV:
- **Right leg**: Has L3+L4 (intact ankle markers), no R3/R4 → RAnkle = NaN
- **Left leg**: Has R3+R4, no L3/L4 → LAnkle = NaN
- **Bilateral**: Has L1/R1 (knee markers), no L3/L4/R3/R4 → both ankles = NaN
- **None**: All L1-L4 and R1-R4 present

### Blade Polygon Editor Workflow

1. Open `blade_editor_*.html` in a browser
2. 3D scatter plot shows all rigid body markers at a representative frame
3. Click markers to assign them to Edge 1 or Edge 2 (in order along the blade)
4. Click "Export JSON" to download `blade_polygon_order.json`
5. Place the JSON in the session's output directory
6. Run `extract_blade_edges.py` to generate `blade_edges.npy` (second command)

### One-Time Preprocessing: Fix Leg Marker Names

P7_2–P7_5 originally used generic marker numbering. A one-time fix was applied:

```bash
# Preview changes
python scripts/fix_leg_marker_names.py --input_dir /Volumes/KINGSTON/P7_mocap --dry_run

# Apply (modifies only the CSV Name header row)
python scripts/fix_leg_marker_names.py --input_dir /Volumes/KINGSTON/P7_mocap --no_backup
```

Verified mapping (confirmed via hardware IDs):
| Generic Name | Correct Name |
|---|---|
| `Lleg:Marker 001` | `Lleg:L1` |
| `Lleg:Marker 004` | `Lleg:L2` |
| `Rleg:Marker 003` | `Rleg:R1` |
| `Rleg:Marker 004` | `Rleg:R2` |

---

## 5. Phase A: One-time Pipeline (P4_1)

Phase A is run once on session P4_1 to establish the shared camera rig calibration. It consists of 9 steps: mcal extraction (A0), GoPro sync (A1), PrimeColor sync (A2), cam19 refinement (A3), frame extraction (A4), stable frame detection (A5), joint calibration (A6), YAML generation (A7), and GT distribution (A8).

### Quick Run (Steps 1-6 Automated)

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline
./run_full_pipeline.sh           # Run all automated steps
./run_full_pipeline.sh --from 3  # Resume from step 3
```

The full pipeline runs steps 1-6 (GoPro sync, PrimeColor sync, frame extraction, stable detection, calibration, YAML generation). Steps A0 (mcal extraction), A3 (cam19 refinement), and A8 (GT symlink + distribution) are manual/interactive and must be run separately.

### Step A0: Create cam19_initial.yaml from .mcal File

Extract PrimeColor camera extrinsics from the OptiTrack .mcal calibration file. This converts from OptiTrack coordinate system (Y-up) to OpenCV (Y-down).

```bash
cd /Volumes/FastACIS/annotation_pipeline
python3 -c "
import codecs, xml.etree.ElementTree as ET, numpy as np, cv2

# Read mcal file (UTF-16-LE with BOM)
with codecs.open('/Volumes/T7/csl/Cal 2026-02-01 14.15.20 Exported.mcal', 'r', 'utf-16-le') as f:
    content = f.read()
if content.startswith('\ufeff'):
    content = content[1:]
root = ET.fromstring(content)

# Find cam19 (CameraID=13 in OptiTrack)
for cam in root.findall('.//Camera'):
    if cam.find('Properties').get('CameraID') != '13':
        continue

    # Extract intrinsics from IntrinsicStandardCameraModel (NOT Intrinsic)
    i = cam.find('IntrinsicStandardCameraModel')
    K = np.array([
        [float(i.get('HorizontalFocalLength')), 0, float(i.get('LensCenterX'))],
        [0, float(i.get('VerticalFocalLength')), float(i.get('LensCenterY'))],
        [0, 0, 1]
    ], dtype=np.float64)
    dist = np.array([[
        float(i.get('k1')), float(i.get('k2')),
        float(i.get('TangentialX')), float(i.get('TangentialY')),
        float(i.get('k3'))
    ]], dtype=np.float64)

    # Extract extrinsics and apply Y-axis flip (OptiTrack Y-up -> OpenCV Y-down)
    e = cam.find('Extrinsic')
    R_m = np.array([
        [float(e.get(f'OrientMatrix{j}')) for j in range(k*3, k*3+3)]
        for k in range(3)
    ], dtype=np.float64)
    pos = np.array([float(e.get('X')), float(e.get('Y')), float(e.get('Z'))])

    Fyz = np.diag([1., -1., -1.])
    R = Fyz @ R_m.T
    rvec, _ = cv2.Rodrigues(R)
    tvec = (-R @ pos).reshape(3, 1)

    # Save to YAML
    out = '/Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/cam19_initial.yaml'
    fs = cv2.FileStorage(out, cv2.FILE_STORAGE_WRITE)
    fs.write('camera_matrix', K)
    fs.write('K', K)
    fs.write('dist_coeffs', dist)
    fs.write('dist', dist)
    fs.write('rvec', rvec)
    fs.write('tvec', tvec)
    fs.write('R', R)
    fs.release()
    print(f'Saved: {out}')
"
```

Key notes:
- The mcal file is UTF-16-LE encoded with BOM
- Use `IntrinsicStandardCameraModel` (not `Intrinsic`) for OpenCV-compatible distortion coefficients
- The Y-axis flip `Fyz = diag(1, -1, -1)` converts OptiTrack (Y-up) to OpenCV (Y-down)
- CameraID=13 in OptiTrack corresponds to cam19 in our pipeline

### Step A1: GoPro QR Sync (16 cameras)

Synchronize all 16 GoPro cameras using a shared QR anchor video. Each GoPro video is scanned for QR codes that encode timestamps, and the common time window is found.

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# Sync all 15 sessions
./run_sync_gopro_batch.sh

# Or sync specific sessions
./run_sync_gopro_batch.sh P4_1 P4_2
```

**How it works:**
1. `sync/sync_gopro_qr_fast.py` extracts frames from each GoPro video
2. Detects QR codes using pyzbar + OpenCV (parallel, downsampled for speed)
3. Maps QR timestamps to video timestamps to compute offset per camera
4. Finds common time window across all cameras
5. Trims videos with ffmpeg to the common window
6. Outputs: synced MP4 files + `meta_info.json` with offsets/durations

**Input:** `/Volumes/FastACIS/csl_11_5/organized/{session}/cam{X}/{session}.MP4`
**Output:** `/Volumes/FastACIS/csl_11_5/synced/{session}_sync/cameras_synced/cam{X}/{session}.MP4`
**Anchor:** `/Volumes/FastACIS/csl_11_5/organized/qr_sync.mp4`

**Skip logic:** If `meta_info.json` already exists in the output directory, the session is skipped.

### Step A2: PrimeColor Sync (cam19)

Synchronize the PrimeColor camera to the GoPro timeline. PrimeColor runs at 120fps and needs to be resampled to 60fps to match the GoPro timeline.

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# Sync all sessions
./run_sync_primecolor_batch.sh

# Or sync specific sessions
./run_sync_primecolor_batch.sh P4_1 P6_4
```

**How it works:**
1. `sync/batch_sync_primecolor.py` iterates over sessions
2. Uses `sync/sync_primecolor_to_gopro_precise.py` for time-based alignment:
   - Reads GoPro `meta_info.json` to get the GoPro timeline
   - Finds PrimeColor video in `/Volumes/T7/csl/{session}/`
   - Computes time mapping between PrimeColor and GoPro timelines
   - Resamples PrimeColor from 120fps to 60fps using ffmpeg
3. Outputs: `primecolor_synced.mp4` + `sync_mapping.json`

**Input:** `/Volumes/T7/csl/{session}/primecolor.mp4` (120fps)
**Output:** `synced/{session}_sync/cameras_synced/cam19/primecolor_synced.mp4` (60fps)
**Mapping:** `synced/{session}_sync/cameras_synced/cam19/sync_mapping.json`

The `sync_mapping.json` contains `offset_seconds` which is used by `refine_extrinsics.py` in SYNC mode to align 120fps mocap markers with 60fps synced video.

### Step A3: Refine cam19 Interactively

Use the interactive marker-pairing tool to refine cam19 extrinsics. This step requires human interaction, clicking on marker positions in the video frame.

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# Convenience mode (cam19 auto-detected as direct mode):
python post_calibration/refine_extrinsics.py \
    --session P4_1 --cam cam19 \
    --markers-base /Volumes/T7/csl \
    --synced-base /Volumes/FastACIS/csl_11_5/synced \
    --camera /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/cam19_initial.yaml
```

Note: `--camera` override is needed here because the initial YAML is `cam19_initial.yaml`, not the default `individual_cam_params/cam19.yaml`.

**Controls:**

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| `a` / `d` | Frame -1 / +1 | `w` / `W` | Frame -2000 / +2000 |
| `s` / `S` | Frame -100 | `D` | Frame +100 |
| `f` | Find stable frame (search forward) | | |
| `[` / `]` | Time offset -1 / +1 | `,` / `.` | Time offset -0.5 / +0.5 |
| L-click | Select marker | R-click | Place correction point |
| `o` | Optimize: solvePnP (extrinsics only, needs 4+ pairs) | | |
| `O` | Optimize: scipy (intrinsics + extrinsics, 14 params, needs 6+ pairs) | | |
| `t` | Toggle Y/Z flip | `z` | Undo last pair |
| `e` | Export YAML + JSON | `r` | Reset all pairs |
| `c` | Cancel current selection | `q` | Quit |

**Marker colors:** Vivid red = stationary markers (good for pairing), faded pink = fast-moving markers (avoid).

**Workflow:**
1. Navigate to a frame where markers are clearly visible
2. Left-click a projected marker circle, then right-click its true position in the image
3. Repeat for 6+ markers spread across the frame
4. Press `O` to optimize (scipy mode recommended for first calibration)
5. Verify projection visually, adjust if needed
6. Press `e` to export the refined YAML

### Step A4: Extract Frames (17 cameras)

Extract image frames from all 17 synced videos for calibration board detection.

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline
./run_extract_frames_parallel.sh
```

**Configuration** (edit in the script):
- `SRC_TAG`: Path to cameras_synced directory
- `FPS=5`: Extract at 5 FPS (sufficient for calibration)
- `START_SEC=334`: Start offset in seconds
- `DURATION=292`: Duration in seconds
- `MAX_PARALLEL=5`: Process 5 cameras simultaneously

**Input:** Synced video files in `cameras_synced/cam{X}/`
**Output:** `cameras_synced/original/cam{X}/frame_XXXX.jpg`

Uses `scripts/convert_video_to_images.py` which calls ffmpeg for frame extraction. Supports both PNG and JPG output with configurable quality.

**Skip logic:** Cameras with 10+ existing images in the output directory are skipped.

### Step A5: Find Stable ChArUco Frames

Detect frames where the ChArUco calibration board is static (low motion) across cameras, then copy a union set of stable frames.

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline
./run_find_and_copy_stable_auto.sh
```

**How it works:**
1. For each camera, `scripts/find_stable_boards.py` detects ArUco markers and interpolates ChArUco corners
2. Computes corner position variance across consecutive frames
3. Filters by movement threshold (< 5.0 pixels) and detection quality (40+ corners for GoPro, 30+ for cam19)
4. Computes the **union** of all per-camera stable frame indices (any frame stable in any camera)
5. Copies union frames from `original/` to `original_stable/` for all 17 cameras

**Configuration:**
- `MOVEMENT_THRESHOLD=5.0`: Maximum corner movement (pixels)
- `MIN_DETECTION_QUALITY=40`: Minimum detected corners (30 for cam19 at 1080p)
- `DOWNSAMPLE_RATE=10`: Process every 10th frame pair for motion check
- `MAX_FRAMES=500`: Maximum frames to output per camera
- Board config: `multical/asset/charuco_b1_2.yaml` (B1 size, 10x14 grid, DICT_7X7_250)

**Input:** `cameras_synced/original/cam{X}/frame_XXXX.jpg`
**Output:** `cameras_synced/original_stable/cam{X}/frame_XXXX.jpg` (union set)
**Summary:** `cameras_synced/stable_frames_detection.json` (per-camera and union frame indices)

P4_1 result: 136 union frames across 17 cameras.

### Step A6: Joint 17-Camera Extrinsic Calibration

Run multical to jointly calibrate all 17 cameras using the stable ChArUco frames with pre-computed intrinsics.

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline
./run_calibration_stable.sh
```

**How it works:**
1. Loads `intrinsic_all_17_cameras.json` with K matrices and distortion coefficients for all 17 cameras
2. Detects ChArUco corners in `original_stable/` across all cameras
3. Runs bundle adjustment to optimize all camera extrinsics jointly
4. `--fix_intrinsic` locks intrinsic parameters, only extrinsics are optimized

**Configuration:**
- `INTRINSIC_FILE`: Path to merged 17-camera intrinsics JSON
- `BOARD_CONFIG`: Path to ChArUco board YAML
- `FIX_INTRINSIC=true`: Lock intrinsics during optimization (recommended)
- `LIMIT_IMAGES=1000`: Maximum images per camera

**Input:** `cameras_synced/original_stable/cam{X}/frame_XXXX.jpg` (17 cameras)
**Output:** `cameras_synced/original_stable/calibration.json`
**Quality:** P4_1 achieved RMS = 1.56 pixels

The `calibration.json` contains `camera_base2cam` with R and T matrices for each camera relative to cam1 (base camera). This file is **shared across all sessions** since the GoPro rig is fixed.

### Step A7: Generate Individual Camera YAML Files

Combine the shared calibration (cam-to-cam) with session-specific cam19 extrinsics (Mocap-to-cam19) to produce individual Mocap-to-camX YAML files for each camera.

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

python post_calibration/generate_individual_cam_yaml.py \
    --calib_json /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/original_stable/calibration.json \
    --cam19_yaml /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/cam19_refined.yaml \
    --output_dir /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/individual_cam_params/
```

**Transform chain per camera:**
```
Mocap -> cam19 (from cam19_refined.yaml)
cam19 -> cam1 (from calibration.json, inverse of cam1's base2cam relative to cam19)
cam1 -> camX (from calibration.json, camX's base2cam)

Combined: Mocap -> camX = (cam1->camX) @ (cam19->cam1) @ (Mocap->cam19)
```

**Input:**
- `calibration.json`: 17-camera joint calibration (R, T per camera relative to cam1)
- `cam19_refined.yaml`: Session-specific Mocap-to-cam19 transform

**Output:** `individual_cam_params/cam{X}.yaml` (17 files), each containing:
- `camera_matrix` / `K`: 3x3 intrinsic matrix
- `dist_coeffs` / `dist`: 1x5 distortion coefficients
- `rvec`: 3x1 rotation vector (Mocap to camera)
- `tvec`: 3x1 translation vector (Mocap to camera)
- `R`: 3x3 rotation matrix (Mocap to camera)

### Step A8: Symlink GT Source Data + Distribute to Per-Camera gt/ Folders

The GT source data (skeleton, blade edges) is stored at 120fps in `/Volumes/T7/csl/{session}/`. The `distribute_gt.py` script expects this data in `cameras_synced/cam19/`, so we create symlinks first, then distribute.

#### A8a: Create Symlinks (one-time setup)

Link GT source files from T7 into each session's cam19/ directory. Note the file renaming: `blade_edges.npy` on T7 is linked as `aligned_edges.npy` (the name `distribute_gt.py` expects).

```bash
# Create symlinks for all 15 sessions
for SESSION in P4_1 P4_2 P4_3 P4_4 P4_5 P5_1 P5_2 P5_3 P5_4 P5_5 P6_1 P6_2 P6_3 P6_4 P6_5; do
    SRC=/Volumes/T7/csl/${SESSION}
    DST=/Volumes/FastACIS/csl_11_5/synced/${SESSION}_sync/cameras_synced/cam19

    # skeleton_h36m.npy (required)
    [ -f "${SRC}/skeleton_h36m.npy" ] && [ ! -e "${DST}/skeleton_h36m.npy" ] && \
        ln -s "${SRC}/skeleton_h36m.npy" "${DST}/skeleton_h36m.npy"

    # blade_edges.npy → aligned_edges.npy (optional, renamed for distribute_gt.py)
    [ -f "${SRC}/blade_edges.npy" ] && [ ! -e "${DST}/aligned_edges.npy" ] && \
        ln -s "${SRC}/blade_edges.npy" "${DST}/aligned_edges.npy"

    echo "${SESSION}: done"
done
```

After this step, each `cam19/` directory contains:
```
cam19/
  primecolor_synced.mp4
  sync_mapping.json
  skeleton_h36m.npy     -> /Volumes/T7/csl/{session}/skeleton_h36m.npy
  aligned_edges.npy     -> /Volumes/T7/csl/{session}/blade_edges.npy
```

IMPORTANT: The T7 volume must be mounted when running `distribute_gt.py`, since symlinks point to T7.

#### A8b: Distribute GT to Per-Camera Folders

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# Single session
python scripts/distribute_gt.py \
    --session_dir /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/

# All sessions at once
for SESSION in P4_1 P4_2 P4_3 P4_4 P4_5 P5_1 P5_2 P5_3 P5_4 P5_5 P6_1 P6_2 P6_3 P6_4 P6_5; do
    python scripts/distribute_gt.py \
        --session_dir /Volumes/FastACIS/csl_11_5/synced/${SESSION}_sync/cameras_synced/ \
        --force
done

# Or use the batch wrapper for specific sessions
./run_distribute_gt.sh P4_1
```

**How it works:**
1. Reads cam19's source GT data at 120fps (via symlinks): `skeleton_h36m.npy` (required), `aligned_edges.npy` (optional), `polygon_vertices.npy` (optional)
2. Reads `sync_mapping.json` to compute the time offset between PrimeColor and GoPro
3. Reads `camera_offsets.json` for per-camera frame offsets (sub-frame corrections). If not present, defaults to 0 for all cameras
4. For each GoPro camera, computes the PrimeColor frame for each GoPro frame:
   ```
   t_gopro = gopro_frame / gopro_fps
   t_prime = t_gopro - offset_seconds + camera_offset / gopro_fps
   prime_frame = round(t_prime * primecolor_fps)
   ```
5. Samples source data at the computed PrimeColor frame index
6. Marks frames outside the PrimeColor range as invalid (NaN + valid_mask=False)

**Input (cam19/):**
- `skeleton_h36m.npy`: (N_prime, 17, 3) at 120fps (required, via symlink from T7)
- `aligned_edges.npy`: (N_prime, E, 2, 3) at 120fps (optional, via symlink from T7's `blade_edges.npy`)
- `polygon_vertices.npy`: (N_prime, V, 3) at 120fps (optional)
- `sync_mapping.json`: PrimeColor-to-GoPro sync parameters
- `camera_offsets.json`: Per-camera frame offsets (in session_dir, optional, default 0)

**Output (per camera):**
```
camX/gt/
  skeleton.npy          (N_gopro, 17, 3)     float32 - 3D joints in Mocap coords
  blade_edges.npy       (N_gopro, E, 2, 3)   float32 - if source exists
  polygon_vertices.npy  (N_gopro, V, 3)      float32 - if source exists
  valid_mask.npy        (N_gopro,)            bool    - frames with valid GT
  gt_info.json          metadata (n_frames, valid range, offsets, source files)
```

**Notes:**
- GT data is in 3D Mocap world coordinates (same across all cameras)
- Without `camera_offsets.json`, all cameras share the same temporal mapping (offset=0). This is acceptable as a first pass; per-camera offsets can be added later and redistributed with `--force`
- Cameras with negative offset (e.g., cam12=-4.5) have their valid range shifted later
- Existing `gt/` folders are skipped unless `--force` is passed
- Use `--output_suffix gt_test` to write to a different folder for testing
- Edge count E varies by session: P4 sessions have E=10, P5/P6 sessions have E=10 or E=15

### Step A9: Verify and Adjust Per-Camera GT Offset

Use the video-playback verification tool to check if the skeleton GT aligns temporally with each GoPro video. The tool pre-loads a short clip into RAM, plays it with skeleton overlay, and lets you adjust the offset and replay instantly.

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# Verify cam1 for P4_1 (10-second clip starting at 60s)
python post_calibration/verify_gt_offset.py \
    --session_dir /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/ \
    --camera cam1 --start 60 --duration 10

# Start at a specific frame instead of seconds
python post_calibration/verify_gt_offset.py \
    --session_dir /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/ \
    --camera cam1 --start_frame 3000 --duration 10
```

**Controls:**

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| `Space` | Play/Replay from start | `p` | Play from current frame |
| `a` / `d` | Frame -1 / +1 | `s` / `D` | Frame -10 / +10 |
| `w` / `W` | Frame -100 / +100 | | |
| `[` / `]` | Camera offset -1 / +1 | `,` / `.` | Camera offset -0.5 / +0.5 |
| `e` | Save offset + redistribute GT | `q` | Quit |
| Trackbar "Offset" | Drag to set offset (range +/-20.0) | Trackbar "Frame" | Seek within clip |

**Workflow:**
1. The tool pre-loads video frames and auto-plays the clip with skeleton overlay
2. Press Space to pause during playback (clip also pauses at end)
3. Adjust offset using `[` `]` keys, `,` `.` for fine steps, or drag the Offset trackbar
4. The current frame updates live as you adjust the offset
5. Press Space to replay the clip with the new offset
6. When satisfied, press `e` to save the offset and automatically redistribute GT for this camera
7. Repeat for each camera

**Output:** `camera_offsets.json` in the session's `cameras_synced/` directory:
```json
{
    "cam1": 2.0,
    "cam2": -1.5,
    "cam3": 0.0
}
```

Pressing `e` automatically saves the offset AND re-runs `distribute_gt.py --force` for the current camera. To manually re-run for all cameras:
```bash
python scripts/distribute_gt.py \
    --session_dir /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/ \
    --force
```

---

## 6. Phase B: Per-session Pipeline

For sessions other than P4_1, only cam19 needs re-calibration since the GoPro rig is fixed.

### Prerequisites

Steps A1-A2 (GoPro sync + PrimeColor sync) must be completed for the target session. If running the full pipeline for the first time, run `./run_full_pipeline.sh` first. For subsequent sessions, run:

```bash
./run_sync_gopro_batch.sh P6_4
./run_sync_primecolor_batch.sh P6_4
```

### Step B1: Refine cam19 for New Session

Use P4_1's cam19_refined.yaml as the initial estimate (the physical setup changes only slightly between sessions).

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# Convenience mode with --camera override (use P4_1's refined yaml as initial estimate)
python post_calibration/refine_extrinsics.py \
    --session P6_4 --cam cam19 \
    --markers-base /Volumes/T7/csl \
    --synced-base /Volumes/FastACIS/csl_11_5/synced \
    --camera /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/cam19_refined.yaml
```

Note: `--camera` override points to **P4_1's** cam19_refined.yaml as the initial estimate. Other paths (video, output, sync) are auto-derived.

### Step B2: Generate Individual YAMLs

Use the **same** calibration.json from P4_1 but with the **new** session's cam19_refined.yaml.

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline
SESSION=P6_4
SYNCED=/Volumes/FastACIS/csl_11_5/synced/${SESSION}_sync/cameras_synced

python post_calibration/generate_individual_cam_yaml.py \
    --calib_json /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/original_stable/calibration.json \
    --cam19_yaml ${SYNCED}/cam19_refined.yaml \
    --output_dir ${SYNCED}/individual_cam_params/
```

### Step B3: (Optional) Refine Individual GoPro

If a specific GoPro's calibration is slightly off, you can refine it independently.

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# Convenience mode: all paths auto-derived from session + cam
python post_calibration/refine_extrinsics.py \
    --session P6_4 --cam cam1 \
    --markers-base /Volumes/T7/csl \
    --synced-base /Volumes/FastACIS/csl_11_5/synced
```

### Batch Processing All Sessions

To process all remaining sessions after P4_1:

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# 1. Ensure all sessions are synced (skips already-synced)
./run_sync_gopro_batch.sh
./run_sync_primecolor_batch.sh

# 2. Refine cam19 for each session (interactive, one at a time)
for SESSION in P4_2 P4_3 P4_4 P4_5 P5_1 P5_2 P5_3 P5_5 P6_1 P6_2 P6_3 P6_4 P6_5; do
    echo "=== Refining cam19 for ${SESSION} ==="
    python post_calibration/refine_extrinsics.py \
        --session ${SESSION} --cam cam19 \
        --markers-base /Volumes/T7/csl \
        --synced-base /Volumes/FastACIS/csl_11_5/synced \
        --camera /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/cam19_refined.yaml
done

# 3. Generate individual YAMLs for all sessions
for SESSION in P4_2 P4_3 P4_4 P4_5 P5_1 P5_2 P5_3 P5_5 P6_1 P6_2 P6_3 P6_4 P6_5; do
    SYNCED=/Volumes/FastACIS/csl_11_5/synced/${SESSION}_sync/cameras_synced
    python post_calibration/generate_individual_cam_yaml.py \
        --calib_json /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/original_stable/calibration.json \
        --cam19_yaml ${SYNCED}/cam19_refined.yaml \
        --output_dir ${SYNCED}/individual_cam_params/
done
```

Note: P5_1 and P5_4 are excluded from cam19 refinement because they lack `body_markers.npy`. P5_4 only has CSV files (needs CSV-to-npy conversion). However, both sessions DO have GT data (`skeleton_h36m.npy`, `blade_edges.npy`) so GT distribution (Step A8) works for all 15 sessions.

### Step B4: Distribute GT (All Sessions)

GT distribution does NOT require cam19 refinement. It only needs `sync_mapping.json` and the GT source symlinks (Step A8a). Run for all sessions:

```bash
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline

# Distribute GT for all 15 sessions (camera_offsets default to 0)
for SESSION in P4_1 P4_2 P4_3 P4_4 P4_5 P5_1 P5_2 P5_3 P5_4 P5_5 P6_1 P6_2 P6_3 P6_4 P6_5; do
    python scripts/distribute_gt.py \
        --session_dir /Volumes/FastACIS/csl_11_5/synced/${SESSION}_sync/cameras_synced/ \
        --force
done
```

---

## 7. Script Reference

### Pipeline Orchestration Scripts (Shell)

| Script | Step | Description |
|--------|------|-------------|
| `run_full_pipeline.sh` | All | Orchestrates steps 1-6 with `--from N` resume |
| `run_sync_gopro_batch.sh` | A1 | Batch GoPro QR sync across sessions |
| `run_sync_primecolor_batch.sh` | A2 | Batch PrimeColor sync across sessions |
| `run_extract_frames_parallel.sh` | A4 | Parallel frame extraction (5 at a time) |
| `run_find_and_copy_stable_auto.sh` | A5 | Stable frame detection + union copy |
| `run_calibration_stable.sh` | A6 | Joint 17-camera extrinsic calibration |
| `run_post_calibration.sh` | A7 | Generate per-camera YAML files |
| `run_distribute_gt.sh` | A8 | Distribute GT from cam19 to per-camera gt/ |
| `run_generate_gt.sh` | Phase 0 | GT data generation from Motive CSV |
| `camera_config.sh` | Config | Camera and session name definitions |

### Workflow Scripts (High-Level, Python)

| Script | Purpose |
|--------|---------|
| `workflow/process_mocap_session.py` | One-command session processor: AVI→MP4 + CSV→skeleton/markers + blade editor HTML |

### GT Data Generation Scripts (Python)

| Script | Purpose |
|--------|---------|
| `scripts/csv2h36m.py` | Motive CSV → skeleton_h36m.npy (17 H36M joints, supports bilateral amputation) |
| `scripts/extract_blade_edges.py` | Motive CSV → blade_edges.npy (ruled surface edges) |
| `scripts/extract_markers.py` | Motive CSV → body_markers.npy (27 Plug-in Gait markers) |
| `scripts/batch_csv2h36m.py` | Batch wrapper for skeleton generation |
| `scripts/batch_extract_blade_edges.py` | Batch wrapper for blade edge extraction |
| `scripts/batch_extract_markers.py` | Batch wrapper for marker extraction |
| `scripts/motive_csv_utils.py` | Shared CSV loading and skeleton prefix detection |
| `scripts/fix_leg_marker_names.py` | One-time: fix generic marker names in P7_2-P7_5 CSVs |

### Synchronization Scripts (Python)

| Script | Purpose |
|--------|---------|
| `sync/sync_gopro_qr_fast.py` | Fast GoPro QR detection (parallel, batch ffmpeg extraction) |
| `sync/sync_with_qr_anchor.py` | Core QR anchor sync logic (offset computation) |
| `sync/sync_primecolor_to_gopro_precise.py` | Time-based PrimeColor-to-GoPro alignment with FPS resampling |
| `sync/batch_sync_primecolor.py` | Batch wrapper for PrimeColor sync across sessions |
| `scripts/sync_timecode.py` | Hardware timecode sync (alternative to QR, for timecode-capable cameras) |
| `scripts/distribute_gt.py` | Distribute GT from cam19 to per-camera gt/ folders with temporal sync |

### Calibration Scripts (Python)

| Script | Purpose |
|--------|---------|
| `scripts/find_stable_boards.py` | Detect frames with static ChArUco board |
| `scripts/convert_video_to_images.py` | Extract frames from video at specified FPS |
| `scripts/copy_image_subset.py` | Copy subset of images (for manual selection) |
| `multical/calibrate.py` | Core multical joint calibration engine |
| `multical/intrinsic.py` | Intrinsic-only calibration |

### Post-Calibration Scripts (Python)

| Script | Purpose |
|--------|---------|
| `post_calibration/refine_extrinsics.py` | Interactive marker-based extrinsic refinement |
| `post_calibration/generate_individual_cam_yaml.py` | Generate per-camera Mocap-to-camera YAML |
| `post_calibration/verify_gt_offset.py` | Interactive per-camera GT temporal offset verification |

### Utility Scripts (Python)

| Script | Purpose |
|--------|---------|
| `tool_scripts/intrinsics_to_fov.py` | Verify calibration by computing FOV |
| `tool_scripts/fov_to_intrinsics.py` | Generate intrinsics from known FOV values |
| `tool_scripts/compare_calibrations.py` | Compare two calibration files |
| `tool_scripts/combine_intrinsic_json.py` | Merge multiple intrinsic JSON files |
| `tool_scripts/check_bone_lengths.py` | Validate 3D skeleton proportions |
| `tool_scripts/convert_images_to_video.py` | Create video from frame sequence |
| `tool_scripts/stack_videos.py` | Create multi-camera stacked video |
| `tool_scripts/trim_videos_with_same_period.py` | Trim videos to matching time range |
| `tool_scripts/qrvideo_generation.py` | Generate QR synchronization reference video |
| `tool_scripts/qrvideo_alignment.py` | Verify QR-based alignment accuracy |

---

## 8. Configuration Reference

### camera_config.sh

```bash
GOPRO_CAMERAS=(cam1 cam2 cam3 cam4 cam5 cam6 cam7 cam8 cam9 cam10 cam11 cam12 cam15 cam16 cam17 cam18)
PRIMECOLOR_CAMERAS=(cam19)
ALL_CAMERAS=("${GOPRO_CAMERAS[@]}" "${PRIMECOLOR_CAMERAS[@]}")
ALL_SETS=(P4_1 P4_2 P4_3 P4_4 P4_5 P5_1 P5_2 P5_3 P5_4 P5_5 P6_1 P6_2 P6_3 P6_4 P6_5)
```

### ChArUco Board (charuco_b1_2.yaml)

- Board type: ChArUco
- Size: B1 paper (10 columns x 14 rows)
- Dictionary: DICT_7X7_250
- Square size: 70mm, Marker size: 50mm

### Intrinsic Parameters

`intrinsic_all_17_cameras.json` contains per-camera entries:
```json
{
  "cam1": {
    "K": [fx, 0, cx, 0, fy, cy, 0, 0, 1],
    "dist": [k1, k2, p1, p2, k3],
    "image_size": [3840, 2160],
    "fov": [hfov, vfov],
    "rms": 0.xx
  },
  ...
  "cam19": { ... }
}
```

GoPro cameras (cam1-cam18): 4K resolution (3840x2160), pre-calibrated with HyperSmooth OFF, Linear lens, 60fps.
PrimeColor cam19: 1080p resolution (1920x1080), intrinsics from mcal file, optimized via scipy during P4_1 refinement.

### Coordinate System Conventions

| System | Convention | Handedness |
|--------|-----------|------------|
| OptiTrack (mcal) | Y-up, Z-forward | Right-handed |
| OpenCV (pipeline) | Y-down, Z-forward | Right-handed |
| Conversion | `Fyz = diag(1, -1, -1)` | Flips Y and Z axes |

Transform from mcal to OpenCV:
```python
Fyz = np.diag([1., -1., -1.])
R_opencv = Fyz @ R_mcal.T
tvec = -R_opencv @ position_mcal
```

---

## 9. Data Format Specifications

### calibration.json

The joint calibration output from multical:
```json
{
  "cameras": {
    "cam1": {"K": [9 floats row-major], "dist": [5 floats]},
    "cam2": {"K": [...], "dist": [...]},
    ...
  },
  "camera_base2cam": {
    "cam1": {"R": [9 floats row-major], "T": [3 floats]},
    "cam2": {"R": [...], "T": [...]},
    ...
  }
}
```

`camera_base2cam` gives transforms relative to cam1 (the base camera). For cam1, R is identity and T is zero.

### cam19_refined.yaml (OpenCV FileStorage)

```yaml
%YAML:1.0
camera_matrix: !!opencv-matrix
  rows: 3
  cols: 3
  data: [fx, 0, cx, 0, fy, cy, 0, 0, 1]
K: !!opencv-matrix
  ...  # Same as camera_matrix
dist_coeffs: !!opencv-matrix
  rows: 1
  cols: 5
  data: [k1, k2, p1, p2, k3]
rvec: !!opencv-matrix
  rows: 3
  cols: 1
  data: [rx, ry, rz]
tvec: !!opencv-matrix
  rows: 3
  cols: 1
  data: [tx, ty, tz]
R: !!opencv-matrix
  rows: 3
  cols: 3
  data: [r00, r01, ..., r22]
```

### sync_mapping.json

PrimeColor-to-GoPro frame synchronization:
```json
{
  "offset_seconds": 12.345,
  "source_fps": 120.0,
  "target_fps": 59.94,
  "total_frames": 17640
}
```

`offset_seconds` is the time offset to add to PrimeColor timestamps to align with GoPro timeline.

### meta_info.json

GoPro QR sync metadata:
```json
{
  "cam1": {"offset": 1.234, "duration": 580.0, "fps": 59.94},
  "cam2": {"offset": 2.345, "duration": 580.0, "fps": 59.94},
  ...
}
```

### stable_frames_detection.json

```json
{
  "per_camera": {
    "cam1": [42, 85, 127, ...],
    "cam2": [42, 85, 130, ...],
    ...
  },
  "union": [42, 85, 127, 130, ...],
  "total_union_frames": 136
}
```

---

## 10. Troubleshooting

### Common Issues

**np.bool deprecation error in multical**
```
AttributeError: module 'numpy' has no attribute 'bool'
```
Fix: Already applied in `csl_pipeline/multical/`. Replace `np.bool` with `bool` in:
- `multical/multical/tables.py`
- `multical/multical/transform/matrix.py`

**Case-sensitive file extension mismatch**
GoPro files are `.MP4` (uppercase), PrimeColor is `.mp4` (lowercase). The FastACIS volume uses case-sensitive APFS. Always use the exact case in scripts.

**cam19 marker projection looks wrong after mcal extraction**
- Check that you used `IntrinsicStandardCameraModel` (not `Intrinsic`) for distortion coefficients
- Verify the Y-axis flip: `Fyz = diag(1, -1, -1)`
- Ensure CameraID mapping is correct (CameraID=13 -> cam19)

**refine_extrinsics.py: markers are all pink/fast-moving**
- Check `--sync` flag points to the correct `sync_mapping.json`
- Verify that `body_markers.npy` matches the session (120fps data)
- Try adjusting time offset with `[` / `]` keys

**Calibration RMS is too high (> 3.0 pixels)**
- Check that `charuco_b1_2.yaml` matches the physical board
- Increase `MIN_DETECTION_QUALITY` threshold
- Reduce `MOVEMENT_THRESHOLD` for stricter stability
- Verify that all cameras can see the board in the extracted time window

**P5_4 has no body_markers.npy**
This session only has CSV files. A CSV-to-npy conversion script is needed. Check the CSV format and extract XYZ columns per marker into the standard npy format.

### Verification Commands

```bash
# Verify sync output exists for a session
ls /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/meta_info.json
ls /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/cam19/sync_mapping.json

# Verify calibration quality
cd /Volumes/FastACIS/annotation_pipeline/csl_pipeline
python tool_scripts/intrinsics_to_fov.py

# Compare two calibrations
python tool_scripts/compare_calibrations.py \
    --calib1 path/to/calibration1.json \
    --calib2 path/to/calibration2.json

# Verify individual YAML files
ls /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/individual_cam_params/
# Should see: cam1.yaml cam2.yaml ... cam19.yaml (17 files)

# Count stable frames
python -c "import json; d=json.load(open('/Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/stable_frames_detection.json')); print(f'Union frames: {d[\"total_union_frames\"]}')"
```

---

## Appendix: csl_pipeline Directory Structure

```
csl_pipeline/
├── WORKFLOW.md                              # This document
├── camera_config.sh                         # Camera and session definitions
├── intrinsic_all_17_cameras.json            # Merged 17-camera intrinsics
├── intrinsic_hyperoff_linear_60fps.json     # GoPro-only intrinsics (reference)
│
├── run_full_pipeline.sh                     # Full pipeline orchestrator
├── run_sync_gopro_batch.sh                  # Step 1: GoPro QR sync
├── run_sync_primecolor_batch.sh             # Step 2: PrimeColor sync
├── run_extract_frames_parallel.sh           # Step 3: Frame extraction
├── run_find_and_copy_stable_auto.sh         # Step 4: Stable frame detection
├── run_calibration_stable.sh                # Step 5: Joint calibration
├── run_post_calibration.sh                  # Step 6: YAML generation
├── run_distribute_gt.sh                     # Step 7: GT distribution
├── run_generate_gt.sh                       # Phase 0: GT data generation
│
├── sync/                                    # Synchronization Python modules
│   ├── sync_gopro_qr_fast.py               #   GoPro QR sync (parallel)
│   ├── sync_with_qr_anchor.py              #   Core QR anchor logic
│   ├── sync_primecolor_to_gopro_precise.py  #   PrimeColor time alignment
│   └── batch_sync_primecolor.py            #   Batch PrimeColor wrapper
│
├── workflow/                                 # High-level workflow tools
│   └── process_mocap_session.py            #   One-command: AVI→MP4 + CSV→GT + blade editor
│
├── scripts/                                 # Data processing scripts
│   ├── find_stable_boards.py               #   Stable ChArUco detection
│   ├── convert_video_to_images.py          #   Frame extraction
│   ├── sync_timecode.py                    #   Hardware timecode sync
│   ├── copy_image_subset.py                #   Image subset selection
│   ├── calculate_world2cam.py              #   World coordinate computation
│   ├── tool_pnp_pairing.py                #   2D-3D pairing GUI
│   ├── distribute_gt.py                    #   GT distribution to per-camera folders
│   ├── csv2h36m.py                         #   Motive CSV → skeleton_h36m.npy
│   ├── extract_blade_edges.py             #   Motive CSV → blade_edges.npy
│   ├── extract_markers.py                 #   Motive CSV → body_markers.npy
│   ├── batch_csv2h36m.py                  #   Batch skeleton generation
│   ├── batch_extract_blade_edges.py       #   Batch blade edge extraction
│   ├── batch_extract_markers.py           #   Batch marker extraction
│   ├── motive_csv_utils.py               #   Shared Motive CSV utilities
│   └── fix_leg_marker_names.py           #   One-time: fix P7 leg marker naming
│
├── post_calibration/                        # Post-calibration refinement
│   ├── refine_extrinsics.py                #   Interactive marker refinement
│   ├── generate_individual_cam_yaml.py     #   Per-camera YAML generation
│   └── verify_gt_offset.py                #   Interactive GT temporal offset verification
│
├── tool_scripts/                            # Utility tools
│   ├── intrinsics_to_fov.py                #   Intrinsics -> FOV
│   ├── fov_to_intrinsics.py                #   FOV -> Intrinsics
│   ├── compare_calibrations.py             #   Diff calibration files
│   ├── combine_intrinsic_json.py           #   Merge intrinsic files
│   ├── check_bone_lengths.py               #   Skeleton validation
│   ├── convert_images_to_video.py          #   Images -> Video
│   ├── stack_videos.py                     #   Multi-camera stacking
│   ├── trim_videos_with_same_period.py     #   Video trimming
│   ├── qrvideo_generation.py               #   QR reference video
│   ├── qrvideo_alignment.py                #   QR alignment verification
│   ├── compare_image_directories.py        #   Image directory diff
│   ├── convert_images_to_lmdb.py           #   Images -> LMDB
│   └── replace_image_with_placeholder.py   #   Image placeholder tool
│
├── multical/                                # Calibration engine (submodule)
│   ├── calibrate.py                        #   Main calibration entry point
│   ├── intrinsic.py                        #   Intrinsic calibration
│   ├── asset/charuco_b1_2.yaml             #   Board definition
│   └── multical/                           #   Core library
│       ├── camera.py, camera_fisheye.py
│       ├── optimization/calibration.py
│       ├── board/charuco.py
│       ├── io/export_calib.py, import_calib.py
│       └── ...
│
└── utils/                                   # Core utility library
    ├── triangulation.py                    #   Multi-view triangulation
    ├── refine_pose3d.py                    #   Temporal pose refinement
    ├── fit_pose3d.py                       #   Optimization-based fitting
    ├── calib_utils.py                      #   Camera undistortion
    ├── constants.py                        #   Configuration constants
    ├── io_utils.py                         #   File I/O utilities
    ├── plot_utils.py                       #   Visualization utilities
    └── logger.py                           #   Logging configuration
```
