# CSL Pipeline Remaining Work Plan

**For: Suginaka-san**
**Created: 2026-02-09**
**Deadline: 2026-02-17**
**Reference: `workflow/P7_complete_workflow_EN.md` for detailed tool usage**

---

## Timeline (Feb 10 PM ~ Feb 16, deliver Feb 17)

### Strategy: Annotate-As-You-Go

Instead of doing all verification first and annotation last, **annotate each participant immediately after its data is ready**. This produces usable results incrementally.

- **P1~P4**: Already fully processed → annotate first (no dependencies)
- **P5**: Verify P5_3~P5_5 → annotate all P5 sessions
- **P6**: Verify P6_1~P6_5 → annotate all P6 sessions
- **P7**: Refine cameras → annotate all P7 sessions
- **P8**: Full pipeline → annotate all P8 sessions (last)

### Time Estimates

| Task | Subtask | Est. Hours | Notes |
|------|---------|-----------|-------|
| **Task 1** | P5_3~P5_5 sync + calibration check | 1.5h | 3 sessions × 30 min |
| | P6_1~P6_5 sync + calibration check | 2.5h | 5 sessions × 30 min |
| | Fix problem cameras (if any) | 1~2h | Copy YAML or re-refine |
| | **Task 1 Total** | **~5h** | |
| **Task 2** | Refine 14 GoPro cameras on P7_4 | 7h | 14 cams × 30 min (marker annotation + optimize) |
| | Copy params + redistribute GT | 1h | Scripted, mostly waiting |
| | Verify sync + fix individual cameras | 2h | Spot-check several sessions |
| | **Task 2 Total** | **~10h** | |
| **Task 3** | Phase 0: Organize P8 data | 1h | Manual file organization |
| | Phase 1: Mocap processing (automated) | 0.5h setup + **2h wait** | Pipeline runs automatically |
| | Phase 1: Blade annotation (manual) | 2.5h | HTML editor, per-session |
| | Phase 2: Blade extraction + cam19 refine | 0.5h + **1h wait** + 1h refine | cam19 marker annotation |
| | Phase 3: GoPro pipeline (automated) | 0.5h setup + **3h wait** | sync + calibration + GT |
| | Phase 4: Verify all P8 sessions | 2h | Sync + calibration check |
| | **Task 3 Total** | **~8h manual + ~6h wait** | Wait time usable for other tasks |
| **Task 4** | Annotation P1~P8 (~36 sessions) | 6h | ~10 min per session |
| | **Task 4 Total** | **~6h** | |
| | **Grand Total** | **~29h manual + ~6h wait** | |

### Daily Schedule

```
═══════════════════════════════════════════════════════════════════════
 Feb 10 (Mon) PM only                                      Day 1
───────────────────────────────────────────────────────────────────────
 PM │ Task 3 Phase 0: Organize P8 data                     [1h]
    │ Task 3 Phase 1: Start mocap processing  ░░░░░░░░░░░  [auto 2h]
    │   ├── while waiting:
    │   │   ★ Annotate P1 (data ready)                     [~1h]
    │   │   ★ Annotate P2 (data ready)                     [~1h]
───────────────────────────────────────────────────────────────────────
 Completed: Task 3 Phase 0 + Phase 1 auto, P1✓ P2✓ annotated
 Hours: ~3h manual
 Annotation progress: ██░░░░░░ P1✓ P2✓

═══════════════════════════════════════════════════════════════════════
 Feb 11 (Tue)                                              Day 2
───────────────────────────────────────────────────────────────────────
 AM │ ★ Annotate P3 + P4 (data ready)                      [~2h]
    │ Task 1: Verify P5_3~P5_5                              [1.5h]
    │
 PM │ ★ Annotate P5 (just verified)                        [~1h]
    │ Task 3 Phase 1: Blade annotation (manual)             [2.5h]
───────────────────────────────────────────────────────────────────────
 Completed: P3✓ P4✓ P5✓ annotated, Task 1 partial
 Hours: ~7h manual
 Annotation progress: █████░░░ P1✓ P2✓ P3✓ P4✓ P5✓

═══════════════════════════════════════════════════════════════════════
 Feb 12 (Wed)                                              Day 3
───────────────────────────────────────────────────────────────────────
 AM │ Task 1: Verify P6_1~P6_5 + fixes                     [3.5h]
    │
 PM │ ★ Annotate P6 (just verified)                        [~1h]
    │ Task 3 Phase 2: Blade extraction  ░░░░░  [auto 1h]
    │ Task 3 Phase 2: cam19 refinement                      [1h]
    │ Task 3 Phase 3: Start GoPro pipeline  ░░░  [auto, runs overnight]
───────────────────────────────────────────────────────────────────────
 Completed: Task 1 done ✓, P6✓ annotated, Task 3 Phase 2+3 started
 Hours: ~5.5h manual
 Annotation progress: ██████░░ P1✓ P2✓ P3✓ P4✓ P5✓ P6✓

═══════════════════════════════════════════════════════════════════════
 Feb 13 (Thu)                                              Day 4
───────────────────────────────────────────────────────────────────────
 AM │ Task 2: Refine P7_4 cameras (cam1~cam8)               [4h]
    │   (Task 3 Phase 3 auto completes during this time)
    │
 PM │ Task 2: Refine P7_4 cameras (cam9~cam18)              [3h]
───────────────────────────────────────────────────────────────────────
 Completed: Task 2 refinement done, Task 3 Phase 3 auto done
 Hours: ~7h manual

═══════════════════════════════════════════════════════════════════════
 Feb 14 (Fri)                                              Day 5
───────────────────────────────────────────────────────────────────────
 AM │ Task 2: Copy params + redistribute GT + verify sync   [2.5h]
    │ Task 2: Fix individual problem cameras                [0.5h]
    │ ★ Annotate P7 (just refined)                         [~1h]
    │
 PM │ Task 3 Phase 4: Verify all P8 sessions                [2h]
    │ ★ Annotate P8 (just verified)                        [~1h]
───────────────────────────────────────────────────────────────────────
 Completed: Task 2 done ✓, Task 3 done ✓, P7✓ P8✓ annotated
 Hours: ~7h manual
 Annotation progress: ████████ P1✓ P2✓ P3✓ P4✓ P5✓ P6✓ P7✓ P8✓

═══════════════════════════════════════════════════════════════════════
 Feb 15~16 (Sat~Sun)                                    Day 6~7
───────────────────────────────────────────────────────────────────────
    │ Final CSV review + consistency check                  [0.5h]
    │ Buffer: re-fix any issues found during annotation     [~2h]
───────────────────────────────────────────────────────────────────────
 Completed: ALL TASKS DONE ✓
═══════════════════════════════════════════════════════════════════════
```

### Key Design Decisions

- **Annotation-first for P1~P4**: Data is already ready, no dependencies. Do these immediately on Day 1~2 to produce early results
- **Verify → Annotate pipeline**: For P5/P6/P7/P8, annotate each participant right after its verification/refinement is done, not in a separate batch later
- **Task 2 (P7 refine) as focused day**: 14 cameras × 30 min is the largest manual block, scheduled as Day 4 without interruption
- **Task 3 automated waits**: ~6h of pipeline wait time filled with annotation (Day 1) and verification (Day 3)
- **Day 6~7 buffer**: Only final review + fixes, all core work finishes by Day 5

---

## Overview

| Participant | Status | Remaining Work |
|------------|--------|----------------|
| P4_1 ~ P5_2 | Done | None |
| P5_3, P5_4, P5_5 | Camera params + GT generated | Calibration & sync verification |
| P6_1 ~ P6_5 | Camera params + GT generated | Calibration & sync verification |
| P7_1 ~ P7_5 | Pipeline complete | Refine individual GoPro params + sync check |
| P8_1 ~ P8_? | Not started | Full pipeline processing |
| P1 ~ P8 (all) | Not started | **Task 4**: Action temporal annotation (cam1 GT overlay → CSV) |

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

## Task 4: Dataset Action Annotation (P1~P8)

Annotate the temporal segments of each action across all sessions (P1 through P8) to create a structured dataset index. The goal is to produce a single CSV file that maps every action to its valid time segments.

### Output Format

A single CSV file: `dataset_annotations.csv` (saved in the project root or a shared location).

Columns:

| action | session | S1 | E1 | S2 | E2 | S3 | E3 | ... |
|--------|---------|-----|-----|-----|-----|-----|-----|-----|
| running on treadmill | P1_1 | 12.5 | 45.0 | 80.2 | 110.0 | | | |
| walking | P1_1 | 120.0 | 155.3 | | | | | |
| running on treadmill | P2_3 | 5.0 | 38.0 | | | | | |

- **action**: Predefined action name (consult experiment protocol for the full list)
- **session**: Which session this action appears in (e.g., P2_3)
- **S1, E1, S2, E2, ...**: Start and end times in **cam1 video seconds** (absolute time from 0:00). Multiple segments allowed if the same action is performed more than once, or if a continuous segment has a quality break in the middle
- Only include segments with **good data quality** (see quality criteria below)

### Step-by-step

For each session (P1_1, P1_2, ..., P8_N):

#### 1. Open cam1 video with GT overlay

```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /Volumes/HumanDATA/Prohuman/synced/PX_Y_sync/cameras_synced \
    --camera cam1 \
    --start 0 \
    --duration -1
```

Use `Space` to play/pause, `[`/`]` to step frame-by-frame.

#### 2. Identify action segments

Watch the video and identify when each predefined action starts and ends. Note the **cam1 video timestamp** (shown in the player) for each start/end point.

#### 3. Check data quality

For each segment, verify the following before recording it:

- **Prosthetic limbs stay in frame**: The blade/prosthetic should remain visible in the cam1 view throughout the segment
- **GT skeleton aligns correctly**: No flying joints, no sudden jumps, no joints stuck at (0,0,0)
- **Subject is performing the expected action**: The motion matches what the action name describes
- **No major occlusions**: The subject's body is reasonably visible

**If a segment has quality issues**: Do NOT include it in the CSV. If only part of a segment is good, split it into sub-segments and only record the good parts (e.g., S1=10, E1=25, S2=30, E2=50 if frames 25-30 are bad).

#### 4. Record to CSV

For each valid action segment, add a row to `dataset_annotations.csv` with:
- The action name
- The session ID (e.g., P3_2)
- Start/end seconds for each valid sub-segment

### Notes

- **Only cam1 is needed** for all annotation work
- The number of sessions varies per participant (not all have 5)
- Check the experiment protocol or video content to determine the full action list for each participant
- It is normal for the same action to appear in multiple sessions, or for one session to contain multiple different actions
- When in doubt about data quality, err on the side of excluding the segment

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

### Dataset Action Annotation
- [ ] Determine the full action list from experiment protocol
- [ ] P1: Annotate all sessions (cam1 GT overlay, record valid segments)
- [ ] P2: Annotate all sessions
- [ ] P3: Annotate all sessions
- [ ] P4: Annotate all sessions
- [ ] P5: Annotate all sessions
- [ ] P6: Annotate all sessions
- [ ] P7: Annotate all sessions
- [ ] P8: Annotate all sessions
- [ ] Final review: check CSV completeness and consistency
