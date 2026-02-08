#!/usr/bin/env python3
"""
Organize GoPro videos from per-camera structure to per-session structure.

Input structure (raw from cameras):
    P7_gopro/
        cam1/
            GX010279.MP4  -> session 1
            GX010280.MP4  -> session 2
            GX010281.MP4  -> session 3
            ...
        cam2/
            GX010276.MP4  -> session 1
            GX010277.MP4  -> session 2
            ...

Output structure (organized by session):
    organized/
        P7_1/
            cam1/
                GX010279.MP4
            cam2/
                GX010276.MP4
            ...
        P7_2/
            cam1/
                GX010280.MP4
            cam2/
                GX010277.MP4
            ...

Usage:
    # Dry run (preview only)
    python workflow/organize_gopro_videos.py \
        --input /Volumes/SSD-EXFAT/P7_gopro \
        --output /Volumes/FastACIS/csl_11_5/organized \
        --participant P7 \
        --dry-run

    # Actually organize (copy files)
    python workflow/organize_gopro_videos.py \
        --input /Volumes/SSD-EXFAT/P7_gopro \
        --output /Volumes/FastACIS/csl_11_5/organized \
        --participant P7

    # Move instead of copy
    python workflow/organize_gopro_videos.py \
        --input /Volumes/SSD-EXFAT/P7_gopro \
        --output /Volumes/FastACIS/csl_11_5/organized \
        --participant P7 \
        --move
"""

import argparse
import shutil
from pathlib import Path
from collections import defaultdict


def natural_sort_key(filename):
    """Extract numeric part from GoPro filename for sorting."""
    # GX010279.MP4 -> 279
    stem = filename.stem  # "GX010279"
    # Extract last digits
    import re
    match = re.search(r'(\d+)$', stem)
    if match:
        return int(match.group(1))
    return 0


def scan_camera_videos(input_dir):
    """Scan all camera directories and collect video files.

    Returns:
        dict: {camera_name: [sorted_video_paths]}
    """
    input_path = Path(input_dir)
    camera_videos = {}

    # Find all cam* directories
    cam_dirs = sorted([d for d in input_path.iterdir()
                      if d.is_dir() and d.name.startswith('cam')])

    for cam_dir in cam_dirs:
        camera_name = cam_dir.name

        # Find all .MP4 files (case insensitive)
        videos = []
        for pattern in ['*.MP4', '*.mp4']:
            videos.extend(cam_dir.glob(pattern))

        # Filter out macOS resource fork files
        videos = [v for v in videos if not v.name.startswith('._')]

        # Sort by filename number
        videos = sorted(videos, key=natural_sort_key)

        if videos:
            camera_videos[camera_name] = videos

    return camera_videos


def validate_sessions(camera_videos):
    """Validate that all cameras have the same number of sessions.

    Returns:
        int: Number of sessions
    Raises:
        ValueError: If cameras have inconsistent session counts
    """
    session_counts = {cam: len(vids) for cam, vids in camera_videos.items()}

    if not session_counts:
        raise ValueError("No videos found in any camera directory")

    unique_counts = set(session_counts.values())
    if len(unique_counts) > 1:
        print("WARNING: Cameras have different numbers of videos:")
        for cam, count in sorted(session_counts.items()):
            print(f"  {cam}: {count} videos")

        # Use the most common count
        from collections import Counter
        most_common_count = Counter(session_counts.values()).most_common(1)[0][0]
        print(f"\nUsing {most_common_count} sessions (most common count)")
        return most_common_count

    return list(unique_counts)[0]


def organize_videos(camera_videos, output_dir, participant, num_sessions,
                    dry_run=False, move=False):
    """Organize videos into per-session structure.

    Args:
        camera_videos: dict of {camera_name: [video_paths]}
        output_dir: Path to output directory
        participant: Participant ID (e.g., "P7")
        num_sessions: Number of sessions
        dry_run: If True, only print what would be done
        move: If True, move files instead of copying
    """
    output_path = Path(output_dir)

    action = "MOVE" if move else "COPY"

    # For each session
    for session_idx in range(num_sessions):
        session_name = f"{participant}_{session_idx + 1}"
        session_dir = output_path / session_name

        print(f"\n{'='*60}")
        print(f"Session {session_idx + 1}: {session_name}")
        print(f"{'='*60}")

        # Create session directory
        if not dry_run:
            session_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created: {session_dir}")
        else:
            print(f"Would create: {session_dir}")

        # For each camera
        for camera_name in sorted(camera_videos.keys()):
            videos = camera_videos[camera_name]

            if session_idx >= len(videos):
                print(f"  {camera_name}: No video for session {session_idx + 1}")
                continue

            src_video = videos[session_idx]
            dst_cam_dir = session_dir / camera_name
            dst_video = dst_cam_dir / src_video.name

            # Create camera directory
            if not dry_run:
                dst_cam_dir.mkdir(parents=True, exist_ok=True)

            # Copy or move video
            size_mb = src_video.stat().st_size / (1024 * 1024)
            print(f"  {camera_name}: {action} {src_video.name} ({size_mb:.1f} MB)")

            if not dry_run:
                if move:
                    shutil.move(str(src_video), str(dst_video))
                else:
                    shutil.copy2(str(src_video), str(dst_video))

                print(f"    -> {dst_video}")


def copy_qr_video(input_dir, output_dir, dry_run=False):
    """Copy QR sync video to organized directory root if it exists.

    Args:
        input_dir: Path to input directory
        output_dir: Path to output directory
        dry_run: If True, only print what would be done
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    # Look for qr_sync video
    qr_patterns = ['qr_sync.mp4', 'qr_sync.MP4', 'QR_sync.mp4', 'QR_sync.MP4']
    qr_video = None

    for pattern in qr_patterns:
        candidate = input_path / pattern
        if candidate.exists():
            qr_video = candidate
            break

    if qr_video:
        dst_qr = output_path / 'qr_sync.mp4'
        size_mb = qr_video.stat().st_size / (1024 * 1024)

        print(f"\n{'='*60}")
        print(f"QR Sync Video")
        print(f"{'='*60}")
        print(f"Found: {qr_video.name} ({size_mb:.1f} MB)")

        if not dry_run:
            shutil.copy2(str(qr_video), str(dst_qr))
            print(f"Copied to: {dst_qr}")
        else:
            print(f"Would copy to: {dst_qr}")
    else:
        print(f"\n{'='*60}")
        print("QR Sync Video: NOT FOUND")
        print("(You may need to add it manually)")
        print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description='Organize GoPro videos from per-camera to per-session structure')
    parser.add_argument('--input', required=True,
                        help='Input directory (e.g., /Volumes/SSD-EXFAT/P7_gopro)')
    parser.add_argument('--output', required=True,
                        help='Output directory (e.g., /Volumes/FastACIS/csl_11_5/organized)')
    parser.add_argument('--participant', required=True,
                        help='Participant ID (e.g., P7)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without actually copying/moving files')
    parser.add_argument('--move', action='store_true',
                        help='Move files instead of copying (default: copy)')

    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)

    # Validate input directory
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    print(f"{'='*60}")
    print(f"GoPro Video Organization")
    print(f"{'='*60}")
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")
    print(f"Participant: {args.participant}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'MOVE' if args.move else 'COPY'}")
    print(f"{'='*60}\n")

    # Step 1: Scan camera videos
    print("Scanning camera directories...")
    camera_videos = scan_camera_videos(input_dir)

    if not camera_videos:
        print("ERROR: No camera videos found!")
        return

    print(f"Found {len(camera_videos)} cameras:")
    for cam in sorted(camera_videos.keys()):
        print(f"  {cam}: {len(camera_videos[cam])} videos")

    # Step 2: Validate session counts
    print("\nValidating session counts...")
    num_sessions = validate_sessions(camera_videos)
    print(f"Number of sessions: {num_sessions}")

    # Step 3: Organize videos
    if args.dry_run:
        print("\n" + "="*60)
        print("DRY RUN MODE - No files will be modified")
        print("="*60)

    organize_videos(camera_videos, output_dir, args.participant, num_sessions,
                    dry_run=args.dry_run, move=args.move)

    # Step 4: Copy QR video
    copy_qr_video(input_dir, output_dir, dry_run=args.dry_run)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Sessions created: {num_sessions}")
    print(f"Cameras per session: {len(camera_videos)}")
    print(f"Total videos: {sum(len(vids) for vids in camera_videos.values())}")

    if args.dry_run:
        print("\nThis was a DRY RUN. Run without --dry-run to actually organize files.")
    else:
        print(f"\nDone! Videos organized in: {output_dir}")


if __name__ == '__main__':
    main()
