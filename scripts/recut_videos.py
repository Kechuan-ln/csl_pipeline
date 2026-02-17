#!/usr/bin/env python
"""
Re-cut P7_2~P7_5 synced videos from organized source using existing meta_info.json offsets.

Usage:
    python scripts/recut_p7_videos.py --sessions P7_2 P7_3 P7_4 P7_5
    python scripts/recut_p7_videos.py --sessions P7_2 --dry-run
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def get_video_size_mb(path):
    return os.path.getsize(path) / (1024 * 1024) if os.path.exists(path) else 0


def recut_session(session, organized_base, synced_base, dry_run=False):
    synced_dir = os.path.join(synced_base, f"{session}_sync", "cameras_synced")
    meta_path = os.path.join(synced_dir, "meta_info.json")

    if not os.path.exists(meta_path):
        print(f"[SKIP] {session}: no meta_info.json")
        return 0, 0

    with open(meta_path) as f:
        meta = json.load(f)

    cameras = meta.get("cameras", {})
    sync_duration = meta.get("sync_duration", None)

    if not cameras:
        print(f"[SKIP] {session}: no camera entries in meta_info.json")
        return 0, 0

    # Compute start_time for each camera: anchor_offset - min(anchor_offsets)
    anchor_offsets = {}
    for cam_key, info in cameras.items():
        cam_name = cam_key.split("/")[0]  # "cam1/GX010280.MP4" -> "cam1"
        anchor_offsets[cam_key] = info["anchor_offset"]

    min_offset = min(anchor_offsets.values())

    success_count = 0
    fail_count = 0

    for cam_key, info in cameras.items():
        cam_name = cam_key.split("/")[0]
        video_filename = cam_key.split("/")[1]

        start_time = info["anchor_offset"] - min_offset
        duration = sync_duration

        # Find source video in organized/
        organized_dir = os.path.join(organized_base, session, cam_name)
        # Find the actual video file (might have different name)
        src_candidates = list(Path(organized_dir).glob("*.MP4")) + list(Path(organized_dir).glob("*.mp4"))
        if not src_candidates:
            print(f"  [SKIP] {cam_name}: no source video in {organized_dir}")
            fail_count += 1
            continue
        src_video = str(src_candidates[0])

        # Output path
        dst_video = os.path.join(synced_dir, cam_name, video_filename)

        old_size = get_video_size_mb(dst_video)

        print(f"  {cam_name}: start={start_time:.2f}s dur={duration:.1f}s src={Path(src_video).name} old={old_size:.0f}MB", end="")

        if dry_run:
            print(" [DRY-RUN]")
            success_count += 1
            continue

        # Backup old video
        if os.path.exists(dst_video):
            backup = dst_video + ".bak"
            os.rename(dst_video, backup)

        # Try stream copy first (fastest, no quality loss)
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(start_time),
            "-i", src_video,
            "-t", str(duration),
            "-c:v", "copy",
            "-c:a", "copy",
            "-movflags", "+faststart",
            dst_video
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0 and os.path.exists(dst_video):
            new_size = get_video_size_mb(dst_video)
            # Verify output is reasonable (>100MB for a multi-minute 4K video)
            if new_size > 100:
                print(f" -> {new_size:.0f}MB [OK]")
                # Remove backup
                backup = dst_video + ".bak"
                if os.path.exists(backup):
                    os.remove(backup)
                success_count += 1
            else:
                print(f" -> {new_size:.0f}MB [TOO SMALL, restoring backup]")
                os.remove(dst_video)
                if os.path.exists(dst_video + ".bak"):
                    os.rename(dst_video + ".bak", dst_video)
                fail_count += 1
        else:
            print(f" [FFMPEG FAILED: {result.stderr[:100]}]")
            # Restore backup
            if os.path.exists(dst_video + ".bak"):
                os.rename(dst_video + ".bak", dst_video)
            fail_count += 1

    return success_count, fail_count


def main():
    parser = argparse.ArgumentParser(description="Re-cut P7 synced videos using stream copy")
    parser.add_argument("--sessions", nargs="+", default=["P7_2", "P7_3", "P7_4", "P7_5"])
    parser.add_argument("--organized-base", default="/Volumes/FastACIS/csl_11_5/organized")
    parser.add_argument("--synced-base", default="/Volumes/FastACIS/csl_11_5/synced")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without executing")
    args = parser.parse_args()

    total_ok = 0
    total_fail = 0

    for session in args.sessions:
        print(f"\n{'='*60}")
        print(f"Processing {session}")
        print(f"{'='*60}")
        ok, fail = recut_session(session, args.organized_base, args.synced_base, args.dry_run)
        total_ok += ok
        total_fail += fail
        print(f"  Result: {ok} OK, {fail} failed")

    print(f"\n{'='*60}")
    print(f"TOTAL: {total_ok} OK, {total_fail} failed")
    if args.dry_run:
        print("(Dry run - no files were modified)")


if __name__ == "__main__":
    main()
