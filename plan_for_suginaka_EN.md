# CSL Pipeline Remaining Work Plan

**For: Suginaka-san**
**Created: 2026-02-09**
**Reference: `workflow/P7_complete_workflow_EN.md` for detailed tool usage**

---

## Overview

| Participant | Status | Remaining Work |
|------------|--------|----------------|
| P4_1 ~ P5_2 | Done | None |
| P5_3, P5_4, P5_5 | Camera params + GT generated | Calibration & sync verification |
| P6_1 ~ P6_5 | Camera params + GT generated | Calibration & sync verification |
| P7_1 ~ P7_5 | Pipeline complete | Refine individual GoPro params + sync check |
| P8_1 ~ P8_? | Not started | Full pipeline processing |

## Data Locations

| Volume | Content | Path Pattern |
|--------|---------|-------------|
| **T7** | P4-P6 Mocap output (skeleton, markers, blade edges, cam19_refined.yaml) | `/Volumes/T7/csl/PX_Y/` |
| **T7** | P7 Mocap output (P7_output) | `/Volumes/T7/P7_output/P7_X/` |
| **HumanDATA** | Synced GoPro videos, calibration, individual cam params, GT folders | `/Volumes/HumanDATA/Prohuman/synced/PX_Y_sync/cameras_synced/` |

---

## Task 1: Verify P5_3, P5_4, P5_5 and P6_1~P6_5

Camera parameters and GT data are already in place for these sessions. You need to verify that:
1. **Calibration (projection)** is correct: skeleton joints align with the person in the video
2. **Synchronization (timing)** is correct: no temporal delay or advance

### Step-by-step

For each session (P5_3, P5_4, P5_5, P6_1, P6_2, P6_3, P6_4, P6_5):

#### 1. Check synchronization

```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /Volumes/HumanDATA/Prohuman/synced/PX_Y_sync/cameras_synced \
    --camera cam1 \
    --start 60 \
    --duration 10
```

- Play the video and check if skeleton overlay is temporally aligned
- If timing is off: use `[` / `]` to adjust offset, then press `e` to save and auto-redistribute GT
- Check a few cameras (cam1, cam5, cam10, etc.) to verify

#### 2. Check calibration (projection quality)

While in the sync verification tool, also check if the skeleton spatially aligns with the person's body (not just timing).

**If calibration looks wrong for a specific camera:**

Follow this troubleshooting strategy:

1. **Try copying params from the previous session**: e.g., if P5_3/cam3 is bad, copy `cam3.yaml` from P5_2's `individual_cam_params/` to P5_3's
2. **If still bad, try the next session**: copy `cam3.yaml` from P5_4's `individual_cam_params/`
3. **If still bad, re-refine**: Run the interactive refinement tool:
   ```bash
   python post_calibration/refine_extrinsics.py \
       --session PX_Y --cam camN \
       --markers-base /Volumes/T7/csl \
       --synced-base /Volumes/HumanDATA/Prohuman/synced
   ```
4. After updating any camera YAML, re-distribute GT for that session

### Special note for P5_4

P5_4 **lacks body_markers.npy**, which means you cannot run `refine_extrinsics.py` on it. If a camera has calibration issues in P5_4:
- Use the corresponding camera YAML from **P5_3** or **P5_5** instead
- Copy the YAML file, verify projection visually, done

### Workflow for fixing a camera

```
Problem detected in PX_Y / camN
    ↓
Copy camN.yaml from PX_(Y-1) → PX_Y/individual_cam_params/
    ↓
Re-visualize → projection OK?
    ├── Yes → Done
    └── No → Copy camN.yaml from PX_(Y+1)
              ↓
              Re-visualize → OK?
              ├── Yes → Done
              └── No → Run refine_extrinsics.py (if body_markers.npy exists)
                        ↓
                        Re-distribute GT
```

---

## Task 2: P7 Individual GoPro Refinement

P7 pipeline is complete (synced videos, calibration, GT distributed). However, the individual GoPro camera parameters have **not been refined** -- they come directly from the joint calibration.

### Step-by-step

#### 1. Refine all GoPro cameras using P7_4

P7_4 has good motion range and body_markers.npy. Refine each GoPro camera (cam1~cam18, skip cam19):

```bash
# For each camera (cam1, cam2, cam3, ..., cam18, skip cam13/cam14):
python post_calibration/refine_extrinsics.py \
    --session P7_4 --cam camN \
    --markers-base /Volumes/T7/P7_output \
    --synced-base /Volumes/HumanDATA/Prohuman/synced
```

For each camera:
1. Press `f` to find a clear frame with visible markers
2. Left-click a 3D marker, right-click the corresponding position in video
3. Annotate at least 6-8 marker pairs
4. Press `O` to optimize (scipy, recommended)
5. Verify with `[`/`]` across frames
6. Press `e` to export

#### 2. Copy refined params to all other P7 sessions

After refining all cameras on P7_4, copy the YAMLs to other sessions:

```bash
# Copy P7_4 individual_cam_params to P7_1, P7_2, P7_3, P7_5
for session in P7_1 P7_2 P7_3 P7_5; do
    cp /Volumes/HumanDATA/Prohuman/synced/P7_4_sync/cameras_synced/individual_cam_params/cam*.yaml \
       /Volumes/HumanDATA/Prohuman/synced/${session}_sync/cameras_synced/individual_cam_params/
done
```

#### 3. Re-distribute GT for all P7 sessions

After updating camera params, GT needs to be re-distributed:

```bash
for session in P7_1 P7_2 P7_3 P7_4 P7_5; do
    python scripts/distribute_gt.py \
        --session_dir /Volumes/HumanDATA/Prohuman/synced/${session}_sync/cameras_synced
done
```

#### 4. Verify synchronization

```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /Volumes/HumanDATA/Prohuman/synced/P7_1_sync/cameras_synced \
    --camera cam1
```

Check several cameras across several sessions. If timing is off, adjust and press `e`.

#### 5. Fix individual problem cameras (if any)

If a specific camera in a specific session looks bad after copying P7_4 params:
- Refine that camera individually for that session
- Or try params from an adjacent session

---

## Task 3: P8 Full Pipeline Processing

P8 is a new participant that needs complete processing from scratch. Mocap data has been exported.

### Prerequisites

1. **Find P8 mocap data**: Check KINGSTON or T7 for the exported Motive data (AVI + CSV + .mcal)
2. **Find P8 GoPro data**: Locate the raw GoPro videos (per-camera structure)

### Step-by-step

Follow the complete workflow in `workflow/P7_complete_workflow_EN.md`, replacing P7 with P8:

#### Phase 0: Data Preparation

1. **Organize mocap data** into the standard structure:
   ```
   P8_mocap/
   ├── P8_1/
   │   ├── *.avi          (PrimeColor video segments)
   │   └── *.csv          (Motive export)
   ├── P8_2/, P8_3/, ...
   └── *.mcal             (OptiTrack calibration, in parent dir)
   ```

2. **Organize GoPro data** from per-camera to per-session:
   ```bash
   python workflow/organize_gopro_videos.py \
       --input /path/to/P8_gopro \
       --output /Volumes/FastACIS/csl_11_5/organized \
       --participant P8 \
       --dry-run
   # Review, then run without --dry-run
   ```

#### Phase 1: Mocap Processing

```bash
python workflow/process_mocap_session.py \
    /path/to/P8_mocap \
    -o /path/to/P8_output \
    --batch
```

Then: open blade HTML editors, annotate edges, export JSON (see workflow doc for details).

#### Phase 2: Blade Extraction + cam19 Refinement

```bash
python workflow/process_blade_session.py \
    /path/to/P8_mocap \
    -o /path/to/P8_output \
    --batch \
    --share_json P8_1
```

Then: run `refine_extrinsics.py` on cam19 (choose session with best motion range).

#### Phase 3: GoPro Complete Pipeline

```bash
python workflow/process_p7_complete.py \
    --organized_dir /Volumes/FastACIS/csl_11_5/organized \
    --mocap_dir /path/to/P8_output \
    --output_dir /Volumes/FastACIS/csl_11_5/synced \
    --anchor_video /Volumes/FastACIS/csl_11_5/organized/qr_sync.mp4 \
    --calibration_session P8_2 \
    --start_time <find_charuco_start> \
    --duration <charuco_duration> \
    --sessions P8_1 P8_2 P8_3 P8_4 P8_5
```

To determine `--calibration_session`, `--start_time`, and `--duration`: open a GoPro video and find where the ChArUco board is stationary. See the "How to Determine" section in the workflow doc.

#### Phase 4: Verification

Same as Tasks 1 and 2 above: verify calibration + sync for all sessions and cameras.

---

## Tips and Tricks

### Interactive Tool Key Reference

| Key | Function |
|-----|----------|
| `f` | Auto-find stable frame (refine_extrinsics) |
| `Space` | Play/pause |
| `[` / `]` | Previous/next frame |
| `,` / `.` | Adjust offset or jump 10 frames |
| `O` | scipy optimization (recommended) |
| `P` | solvePnP optimization |
| `e` | Export / save |
| `u` | Undo last marker pair |
| `c` | Clear all pairs |
| `q` | Quit |

### When to Ask AI for Help

- If `refine_extrinsics.py` won't converge (error stays high after 8+ marker pairs)
- If you're unsure which `--start_time`/`--duration` to use for P8 calibration
- If GT distribution fails or produces unexpected results
- For any command syntax questions, refer to `workflow/P7_complete_workflow_EN.md`

---

## Checklist

### P5 + P6 Verification
- [ ] P5_3: sync check + calibration check
- [ ] P5_4: sync check + calibration check (no refine possible, use P5_3/P5_5 params if needed)
- [ ] P5_5: sync check + calibration check
- [ ] P6_1: sync check + calibration check
- [ ] P6_2: sync check + calibration check
- [ ] P6_3: sync check + calibration check
- [ ] P6_4: sync check + calibration check
- [ ] P6_5: sync check + calibration check

### P7 Refinement
- [ ] Refine all GoPro cameras on P7_4 (cam1~cam18, skip cam13/14/19)
- [ ] Copy refined params to P7_1, P7_2, P7_3, P7_5
- [ ] Re-distribute GT for all P7 sessions
- [ ] Verify sync for P7 sessions
- [ ] Fix any individual problem cameras

### P8 Full Processing
- [ ] Locate and organize P8 mocap data
- [ ] Locate and organize P8 GoPro data
- [ ] Phase 1: Mocap processing + blade annotation
- [ ] Phase 2: Blade extraction + cam19 refinement
- [ ] Phase 3: GoPro pipeline (sync + calibration + GT)
- [ ] Verify calibration + sync for all P8 sessions
