#!/usr/bin/env python3
"""
Fast batch sync of Primecolor (cam19) videos to GoPro timeline.

Optimizations vs running sync_primecolor_to_gopro_precise.py in a loop:
  1. Anchor video scanned ONCE (not 15 times)
  2. GoPro QR scan SKIPPED entirely (offset derived from meta_info.json)
  3. PrimeColor scan uses larger frame_step for faster detection

Usage:
    python batch_sync_primecolor.py --synced_base /path/to/synced --primecolor_base /path/to/primecolor
    python batch_sync_primecolor.py --synced_base /path/to/synced --primecolor_base /path/to/primecolor --sets P4_1 P5_3
    python batch_sync_primecolor.py --synced_base /path/to/synced --primecolor_base /path/to/primecolor --gpu
"""

import os
import sys
import json
import time
import argparse
import numpy as np
from dataclasses import asdict

# Add sync/ directory to path (this file lives inside sync/)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sync_with_qr_anchor import (
    scan_video_qr_segment,
    get_anchor_time,
    get_video_info,
)
from sync_primecolor_to_gopro_precise import (
    SyncMapping,
    create_synced_video_precise,
    build_frame_mapping,
)

ALL_SETS = [
    "P4_1", "P4_2", "P4_3", "P4_4", "P4_5",
    "P5_1", "P5_2", "P5_3", "P5_4", "P5_5",
    "P6_1", "P6_2", "P6_3", "P6_4", "P6_5",
]


def get_gopro_offset_from_meta(meta_path: str) -> tuple:
    """
    Derive gopro_offset_synced from meta_info.json without scanning video.

    Returns:
        (gopro_offset_synced, gopro_fps, gopro_duration, gopro_frames, cam1_video_path)
    """
    with open(meta_path) as f:
        meta = json.load(f)

    # Find cam1 entry
    cam1_key = None
    for key in meta["cameras"]:
        if key.startswith("cam1/"):
            cam1_key = key
            break

    if cam1_key is None:
        raise ValueError(f"No cam1 entry found in {meta_path}")

    cam1 = meta["cameras"][cam1_key]
    gopro_offset_synced = cam1["anchor_offset"] - cam1["sync_offset"]

    # Get video info from the synced cam1 file
    cam1_dir = os.path.dirname(meta_path)
    cam1_video = os.path.join(cam1_dir, cam1_key)
    gopro_info = get_video_info(cam1_video)

    return (
        gopro_offset_synced,
        gopro_info["fps"],
        gopro_info["duration"],
        gopro_info["frame_count"],
        cam1_video,
    )


def process_set(
    set_name: str,
    anchor_map: dict,
    anchor_fps: float,
    synced_base: str,
    primecolor_base: str,
    use_gpu: bool = False,
    frame_step: int = 15,
    min_detections: int = 15,
    scan_duration: float = 120.0,
) -> bool:
    """Process a single set. Returns True on success."""
    print(f"\n{'=' * 80}")
    print(f"  [{set_name}]")
    print(f"{'=' * 80}")

    meta_path = os.path.join(synced_base, f"{set_name}_sync", "cameras_synced", "meta_info.json")
    primecolor_video = os.path.join(primecolor_base, set_name, "video.mp4")
    output_dir = os.path.join(synced_base, f"{set_name}_sync", "cameras_synced", "cam19")
    output_video = os.path.join(output_dir, "primecolor_synced.mp4")

    # Resume check
    if os.path.exists(output_video):
        print(f"  Already synced, skipping. (delete cam19/ to re-run)")
        return True

    # Validate inputs
    if not os.path.exists(meta_path):
        print(f"  ERROR: meta_info.json not found at {meta_path}")
        return False
    if not os.path.exists(primecolor_video):
        print(f"  ERROR: Primecolor video not found at {primecolor_video}")
        return False

    os.makedirs(output_dir, exist_ok=True)

    # Step 1: GoPro offset from meta_info.json (instant)
    print(f"\n  Step 1: Reading GoPro offset from meta_info.json")
    gopro_offset_synced, gopro_fps, gopro_duration, gopro_frames, cam1_video = \
        get_gopro_offset_from_meta(meta_path)
    print(f"    gopro_offset_synced = {gopro_offset_synced:.6f}s")
    print(f"    GoPro: {gopro_fps:.2f}fps, {gopro_duration:.2f}s")

    # Step 2: Scan PrimeColor for QR codes
    print(f"\n  Step 2: Scanning PrimeColor video (step={frame_step}, min={min_detections})")
    primecolor_detections = scan_video_qr_segment(
        primecolor_video,
        start_time=0.0,
        duration=scan_duration,
        frame_step=frame_step,
        prefix="",
        min_detections=min_detections,
        early_stop=True,
    )
    primecolor_info = get_video_info(primecolor_video)
    print(f"    Detected {len(primecolor_detections)} QR codes")
    print(f"    PrimeColor: {primecolor_info['fps']:.2f}fps, {primecolor_info['duration']:.2f}s")

    if not primecolor_detections:
        print(f"  ERROR: No QR codes detected in PrimeColor video")
        return False

    # Step 3: Compute offset
    print(f"\n  Step 3: Computing time offset")
    primecolor_offsets = []
    for video_time, qr_num in primecolor_detections:
        anchor_time = get_anchor_time(qr_num, anchor_map, anchor_fps)
        primecolor_offsets.append(video_time - anchor_time)

    primecolor_offset = float(np.median(primecolor_offsets))
    primecolor_std = float(np.std(primecolor_offsets))
    offset_seconds = gopro_offset_synced - primecolor_offset
    offset_std = primecolor_std  # gopro side has no variance (from JSON)

    print(f"    PrimeColor offset to anchor: {primecolor_offset:.6f}s (std: {primecolor_std:.4f}s)")
    print(f"    Final offset: {offset_seconds:.6f}s")

    if primecolor_std > 0.1:
        print(f"    WARNING: High std, possible detection errors or drift")

    # Step 4: Build mapping and create video
    output_duration = gopro_duration

    # Check overlap
    primecolor_start = max(0, offset_seconds)
    primecolor_end = min(output_duration, primecolor_info["duration"] + offset_seconds)
    if primecolor_end <= primecolor_start:
        print(f"  ERROR: No overlapping time range")
        return False

    mapping = SyncMapping(
        offset_seconds=offset_seconds,
        gopro_offset_to_anchor=gopro_offset_synced,
        primecolor_offset_to_anchor=primecolor_offset,
        gopro_fps=gopro_fps,
        primecolor_fps=primecolor_info["fps"],
        target_fps=gopro_fps,
        gopro_duration=gopro_duration,
        primecolor_duration=primecolor_info["duration"],
        output_duration=output_duration,
        gopro_frames=gopro_frames,
        primecolor_frames=primecolor_info["frame_count"],
        output_frames=int(output_duration * gopro_fps),
        gopro_qr_count=0,  # not scanned
        primecolor_qr_count=len(primecolor_detections),
        offset_std=offset_std,
    )

    frame_mapping = build_frame_mapping(
        mapping.gopro_fps,
        mapping.primecolor_fps,
        mapping.offset_seconds,
        mapping.output_duration,
        mapping.primecolor_duration,
    )
    mapping.frame_mapping_sample = {k: v for k, v in frame_mapping.items() if k % 100 == 0}

    print(f"\n  Step 4: Creating synced video")
    video_success = create_synced_video_precise(
        primecolor_video, output_video, mapping, use_gpu=use_gpu
    )

    # Save mapping JSON
    mapping_json = os.path.join(output_dir, "sync_mapping.json")
    with open(mapping_json, "w") as f:
        json.dump(asdict(mapping), f, indent=2)
    print(f"  Saved: {mapping_json}")

    if video_success:
        print(f"  [{set_name}] SUCCESS")
    else:
        print(f"  [{set_name}] FAILED (video encoding)")

    return video_success


def main():
    parser = argparse.ArgumentParser(
        description="Fast batch sync Primecolor (cam19) to GoPro timeline"
    )
    parser.add_argument("--synced_base", required=True,
                        help="Base dir of synced GoPro output (e.g. /Volumes/FastACIS/csl_11_5/synced)")
    parser.add_argument("--primecolor_base", required=True,
                        help="Base dir of PrimeColor raw videos (e.g. /Volumes/T7/csl)")
    parser.add_argument("--sets", nargs="+", default=None,
                        help="Specific sets to process (default: all 15)")
    parser.add_argument("--gpu", action="store_true",
                        help="Use VideoToolbox GPU encoding (macOS)")
    parser.add_argument("--frame_step", type=int, default=15,
                        help="QR scan frame step (default: 15)")
    parser.add_argument("--min_detections", type=int, default=15,
                        help="Min QR detections before early stop (default: 15)")
    parser.add_argument("--scan_duration", type=float, default=120.0,
                        help="Max QR scan duration in seconds (default: 120)")
    args = parser.parse_args()

    sets = args.sets if args.sets else ALL_SETS

    print("=" * 80)
    print("Fast Batch Primecolor (cam19) Sync")
    print("=" * 80)
    print(f"Sets: {', '.join(sets)}")
    print(f"GPU encoding: {args.gpu}")
    print(f"QR scan: step={args.frame_step}, min_detections={args.min_detections}")

    # Step 0: Anchor metadata — skip scanning entirely.
    # The QR video is generated with sequential frame numbers at 30fps,
    # so get_anchor_time(qr_num, None, 30.0) = qr_num / 30.0 (exact).
    anchor_map = None
    anchor_fps = 30.0
    print(f"\n  Anchor: using formula (qr_num / {anchor_fps}fps), no video scan needed")

    # Process each set
    success = 0
    fail = 0
    skip = 0
    total_start = time.time()

    for set_name in sets:
        t_set = time.time()

        output_video = os.path.join(
            args.synced_base, f"{set_name}_sync", "cameras_synced", "cam19", "primecolor_synced.mp4"
        )
        if os.path.exists(output_video):
            print(f"\n  [{set_name}] Already synced, skipping.")
            skip += 1
            continue

        ok = process_set(
            set_name,
            anchor_map,
            anchor_fps,
            synced_base=args.synced_base,
            primecolor_base=args.primecolor_base,
            use_gpu=args.gpu,
            frame_step=args.frame_step,
            min_detections=args.min_detections,
            scan_duration=args.scan_duration,
        )

        elapsed = time.time() - t_set
        if ok:
            success += 1
            print(f"  [{set_name}] Done in {elapsed:.0f}s")
        else:
            fail += 1
            print(f"  [{set_name}] Failed after {elapsed:.0f}s")

    total_elapsed = time.time() - total_start

    print(f"\n{'=' * 80}")
    print("Summary")
    print(f"{'=' * 80}")
    print(f"  Total:   {len(sets)}")
    print(f"  Success: {success}")
    print(f"  Skipped: {skip}")
    print(f"  Failed:  {fail}")
    print(f"  Time:    {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"{'=' * 80}")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
