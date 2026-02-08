# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-camera synchronization and calibration pipeline for a biomechanics motion capture system. Processes 16 GoPro cameras (60fps, 4K) + 1 PrimeColor OptiTrack camera (120fps) to produce per-camera extrinsic calibrations and distribute ground truth (GT) data from mocap to each camera view.

Target application: 3D human motion capture with prosthetic subjects (bilateral amputees), tracking skeleton joints, blade edges, and body markers.

## Running the Pipeline

```bash
# Activate environment
conda activate multical

# Full pipeline (steps 1-7)
./run_full_pipeline.sh

# Resume from a specific step
./run_full_pipeline.sh --from 3

# Individual steps
./run_sync_gopro_batch.sh          # Step 1: GoPro QR sync
./run_sync_primecolor_batch.sh     # Step 2: PrimeColor time-based sync
./run_extract_frames_parallel.sh   # Step 3: Frame extraction at 5 FPS
./run_find_and_copy_stable_auto.sh # Step 4: Stable ChArUco detection
./run_calibration_stable.sh        # Step 5: Joint extrinsic calibration (multical)
./run_post_calibration.sh          # Step 6: Per-camera YAML generation
./run_distribute_gt.sh --all       # Step 7: GT distribution to all cameras

# GT generation (Phase 0, run separately - requires T7 volume)
./run_generate_gt.sh

# P7+ one-command mocap processing (AVI concat + CSV → GT)
python workflow/process_mocap_session.py <session_dir>

# Interactive extrinsic refinement
python post_calibration/refine_extrinsics.py
```

Calibration validation target: RMS reprojection error < 1.6px for P4_1.

## Architecture

### Two-Phase Design

The GoPro rig is physically fixed between sessions, so the pipeline avoids full re-calibration:

- **Phase A (one-time, on P4_1)**: Full 17-camera joint calibration → `calibration.json`
- **Phase B (per-session)**: Only refine cam19 (PrimeColor) extrinsics → `cam19_refined.yaml`, then combine with shared `calibration.json`

### Transform Chain

```
Mocap world → cam19 (PrimeColor, OptiTrack-calibrated)
  → cam1 (GoPro base camera)
  → camX (other GoPros)

Per-camera YAML = (cam1→camX) @ (cam19→cam1) @ (Mocap→cam19)
```

### GT Temporal Mapping

Frame mapping from GoPro (60fps) to PrimeColor mocap (120fps):
```
t_gopro = frame_gopro / fps_gopro
t_prime = t_gopro - offset_seconds - camera_offset / fps_gopro
prime_frame = round(t_prime * fps_primecolor)
```
`offset_seconds` comes from `sync_mapping.json`; per-camera sub-frame corrections from `camera_offsets.json`.

### Coordinate System

OptiTrack uses Y-up; OpenCV uses Y-down. Conversion requires `Fyz = diag(1, -1, -1)` applied to the rotation matrix.

## Key Directories

| Directory | Purpose |
|-----------|---------|
| `sync/` | Video synchronization (QR anchor for GoPros, time-based for PrimeColor) |
| `scripts/` | Core data processing (CSV→H36M, blade edges, markers, frame extraction, GT distribution) |
| `post_calibration/` | Interactive refinement tools and per-camera YAML generation |
| `multical/` | Multi-camera calibration library (submodule, bundle adjustment + ChArUco detection) |
| `utils/` | Shared utilities (triangulation, pose refinement, camera undistortion, I/O) |
| `tool_scripts/` | Standalone validation and conversion tools |
| `workflow/` | High-level session processing (P7+ AVI concat + GT generation) |

## Key Configuration Files

| File | Purpose |
|------|---------|
| `camera_config.sh` | Camera array definitions (16 GoPro + 1 PrimeColor) and 15 session IDs. Sourced by all bash scripts |
| `intrinsic_all_17_cameras.json` | Pre-calibrated intrinsics (K matrices + distortion) for all 17 cameras |
| `multical/asset/charuco_b1_2.yaml` | ChArUco board spec (7x9 grid, DICT_5X5_100) |

## Important Patterns

- **cam13 and cam14 are unused** - the 16 GoPros are cam1-cam12 + cam15-cam18
- **Auto-amputation detection**: `csv2h36m.py` detects bilateral/left/right amputation from marker naming (L3/L4/R3/R4 presence) and sets ankle joints to NaN
- **Blade edge resampling**: Uses arc-length parameterization (not linear interpolation) for uniform spacing
- **Sparse pose table**: `multical/` handles missing ChArUco detections gracefully; invalid entries skipped during optimization
- **QR sync optimization**: Coarse 2-second sampling until 20 QR codes found, then fine scanning on overlap regions; ~4-6 min per session
- **Interactive refinement has two modes**: `solvePnP` (extrinsics only, 4+ marker pairs) or `scipy.least_squares` (all 14 params, 6+ pairs)

## Data Volumes

- **FastACIS** (`/Volumes/FastACIS/csl_11_5/`): GoPro videos (organized + synced), calibration outputs
- **T7** (`/Volumes/T7/csl/`): Mocap data (Motive CSV, PrimeColor video, GT arrays)
- **KINGSTON**: P7+ raw data (AVI segments + CSV, requires concatenation via `process_mocap_session.py`)

## Dependencies

Python 3.6+ with conda environment `multical`. Key packages: `numpy`, `scipy`, `opencv-contrib-python>=4.5.0`, `aniposelib` (triangulation), `pyzbar` (QR detection), `numba`, `numpy-quaternion`. System dependency: `ffmpeg`/`ffprobe`.

Install multical in development mode: `pip install -e multical/`

## Detailed Documentation

See `WORKFLOW.md` for the complete 1400-line pipeline guide covering all phases, data formats, configuration schemas, and troubleshooting.
