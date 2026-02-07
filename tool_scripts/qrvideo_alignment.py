#!/usr/bin/env python3
"""
Camera Synchronization Tool Based on Anchor QR Code Video (Enhanced Version)

Core Concept:
- Use QR code video with known time sequence as anchor (reference baseline)
- Two cameras record the QR code video, even if they see different QR code sequences
- Calculate relative time offset between the two cameras through anchor timecode mapping

How it Works:
1. Camera1 sees QR code #100 at time t1
2. Camera2 sees QR code #150 at time t2
3. From anchor metadata: QR#100 corresponds to anchor time T1, QR#150 corresponds to anchor time T2
4. Calculate offset: offset = (t1 - T1) - (t2 - T2)
"""

import cv2
import numpy as np
import os
import json
import argparse
import glob
import subprocess

import csv
from tqdm import tqdm
import shutil
from typing import List, Tuple, Optional, Dict

try:
    import pyzbar
    HAS_PYZBAR = True
except ImportError:
    HAS_PYZBAR = False

import sys
sys.path.append('..')
from utils.calib_utils import get_fps, extract_framewise_timestamps, get_video_length
from utils.io_utils import convert_video_to_images
from utils.constants import PATH_ASSETS_VIDEOS, IMG_FORMAT_IO

USE_START_TIME_STAMP = False
START_TIME_STAMP= {
    'cam1': 23.0,
    'cam5': 33.0,
    'cam10': 45.0,
    'cam15': 54.0,
}

def detect_qr_fast(frame: np.ndarray) -> List[str]:
    """
    Fast QR detection (supports pyzbar and OpenCV dual engines)
    """
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame

    # Downsample for speed
    if gray.shape[0] > 1080:
        scale = 1080.0 / gray.shape[0]
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    results = []

    # Prioritize pyzbar
    if HAS_PYZBAR:
        try:
            detected = pyzbar.decode(gray, symbols=[pyzbar.ZBarSymbol.QRCODE])
            if detected:
                for obj in detected:
                    results.append(obj.data.decode('utf-8'))
        except:
            pass

    # Fallback: OpenCV
    if not results:
        try:
            detector = cv2.QRCodeDetector()
            data, vertices, _ = detector.detectAndDecode(gray)
            if data:
                results.append(data)
        except:
            pass

    return results


def parse_qr_frame_number(qr_data: str, prefix: str = "") -> Optional[int]:
    """
    Parse QR code and extract frame number

    Args:
        qr_data: QR code data (e.g., "000042" or "SYNC-000042")
        prefix: Expected prefix (e.g., "SYNC-")

    Returns:
        Frame number (integer), returns None if parsing fails
    """
    
    if prefix and qr_data.startswith(prefix):
        qr_data = qr_data[len(prefix):]
    frame_num = int(qr_data)
    return frame_num
    

def extract_anchor_metadata_from_video(video_path: str,
                                        prefix: str = "",) -> Dict[int, float]:
    """
    Extract metadata from anchor QR code video with caching

    Processes entire video, extracts all frames, reads QR codes, and caches results to CSV.
    Note: anchor_start, num_samples, frame_step are ignored in this implementation.

    Args:
        video_path: Anchor video path
        prefix: QR code prefix

    Returns:
        anchor_map: Dictionary mapping {qr_frame_num: pts_time}
    """

    print(f"Extract metadata from anchor video: {os.path.basename(video_path)}")

    # Check for cached CSV file
    cache_csv_path = os.path.splitext(video_path)[0] + '_anchor_cache.csv'

    if os.path.exists(cache_csv_path):
        print(f"  ✅ Loading cached anchor metadata from {os.path.basename(cache_csv_path)}")
        anchor_map = {}
        with open(cache_csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                qr_frame_num = int(row['qr_frame_num'])
                pts_time = float(row['pts_time'])
                anchor_map[qr_frame_num] = pts_time

        print(f"  Loaded {len(anchor_map)} QR code mappings from cache")
        qr_numbers = sorted(anchor_map.keys())
        print(f"  QR code range: {qr_numbers[0]} - {qr_numbers[-1]}")
        return anchor_map

    # Cache doesn't exist, extract from video
    print(f"  No cache found, extracting anchor metadata from entire video...")

    # Get video info
    fps = get_fps(video_path)
    duration = get_video_length(video_path)
    print(f"  Video info: {fps:.2f}fps, {duration:.2f}s")

    # Extract all frames to temporary folder
    # Create temporary directory
    temp_dir = os.path.join(os.path.dirname(video_path), 'temp_qr_frames')
    os.makedirs(temp_dir, exist_ok=True)

    # Step 1: Get ALL timestamps from video
    print(f"  Extracting all timestamps from video...")
    frame_timestamps = extract_framewise_timestamps(video_path, ss=None, duration=None)

    print(f"  Found {len(frame_timestamps)} frames total")
    print(f"  Extracting frames at exact timestamps to detect QR codes...")

    anchor_map = {}

    # Step 2: Extract each frame by exact frame index
    for i, ts in tqdm(enumerate(frame_timestamps), total=len(frame_timestamps), desc="  Extracting & scanning frames"):
        output_path = os.path.join(temp_dir, f"frame_{i:08d}.jpg")

        # Extract frame by exact frame number using ffmpeg select filter
        # This is more accurate than -ss timestamp seeking
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-vf', f"select='eq(n\\,{i})'",
            '-vsync', '0',
            '-frames:v', '1',
            '-q:v', '1',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True)

        if result.returncode != 0:
            print(f"  ⚠️ Warning: Failed to extract frame {i} at {ts:.3f}s")
            continue

        # Read frame
        frame = cv2.imread(output_path)
        if frame is None:
            print(f"  ⚠️ Warning: Failed to read frame {i} at {ts:.3f}s")
            continue

        # Detect QR codes
        qr_codes = detect_qr_fast(frame)

        if len(qr_codes) > 0:
            assert len(qr_codes) < 2, f"Multiple QR codes detected at frame {i} (timestamp {ts:.3f}s)!"
            qr_data = qr_codes[0]
            qr_frame_num = parse_qr_frame_number(qr_data, prefix)

            if qr_frame_num is not None:
                # Verify that QR frame number matches the frame index
                assert qr_frame_num == i, f"QR frame number {qr_frame_num} doesn't match frame index {i}"

                # Perfect alignment: frame i at timestamp ts has QR code qr_frame_num
                anchor_map[qr_frame_num] = ts
        else:
            # This is expected for anchor videos - not every frame has a QR code
            pass


    print(f"\n  ✅ Extracted {len(anchor_map)} QR code mappings")

    # Save to cache CSV
    print(f"  Saving anchor metadata to cache: {os.path.basename(cache_csv_path)}")
    with open(cache_csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['qr_frame_num', 'pts_time'])
        writer.writeheader()
        for qr_frame_num in sorted(anchor_map.keys()):
            writer.writerow({
                'qr_frame_num': qr_frame_num,
                'pts_time': anchor_map[qr_frame_num]
            })


    shutil.rmtree(temp_dir, ignore_errors=True)
    print(f"  🧹 Cleaned up temporary frames")

    # Verify QR code sequence
    qr_numbers = sorted(anchor_map.keys())
    print(f"  QR code range: {qr_numbers[0]} - {qr_numbers[-1]}")
    return anchor_map


def scan_video_qr_segment(video_path: str,
                          start_time: float = 0.0,
                          duration: float = 60.0,
                          frame_step: int = 5,
                          prefix: str = "") -> List[Tuple[float, int]]:
    """
    Scan QR codes in video segment

    Args:
        video_path: Video path
        start_time: Start time (seconds)
        duration: Scan duration (seconds)
        frame_step: Frame interval
        prefix: QR code prefix

    Returns:
        [(video_time, qr_frame_number), ...] list
    """
    print(f"Scan:  {video_path}")
    print(f"  Time segment: {start_time:.1f}s - {start_time + duration:.1f}s")

    # Get video metadata
    fps = get_fps(video_path)
    video_duration = get_video_length(video_path)

    print(f"  Video info: {fps:.2f}fps, {video_duration:.2f}s")

    # Validate time range
    if start_time >= video_duration:
        print(f"  ⚠️ Start time exceeds video duration")
        return {}, video_duration

    # Extract frames to temporary folder
    temp_dir = os.path.join(os.path.dirname(video_path), 'temp_qr_frames')
    os.makedirs(temp_dir, exist_ok=True)

    # Step 1: Get ALL timestamps from video
    print(f"  Extracting timestamps from entire video...")
    all_timestamps = extract_framewise_timestamps(video_path, ss=None, duration=None)

    # Step 2: Filter to desired time range, keeping frame indices
    frame_indices_and_timestamps = [(idx, ts) for idx, ts in enumerate(all_timestamps)
                                    if start_time <= ts < start_time + duration]

    print(f"  Filtered to {len(frame_indices_and_timestamps)} frames in time range [{start_time:.2f}s - {start_time+duration:.2f}s)")
    print(f"  Extracting frames by exact frame index with step={frame_step}...")

    # Step 3: Extract frames by exact frame index (with frame_step)
    seen_qr_frames = {}

    # Extract frames at specific indices
    for i in tqdm(range(0, len(frame_indices_and_timestamps), frame_step), desc="  Extracting & scanning frames"):
        frame_idx, ts = frame_indices_and_timestamps[i]
        output_path = os.path.join(temp_dir, f"frame_{frame_idx:08d}.jpg")

        # Extract frame by exact frame number using ffmpeg select filter
        # This is more accurate than -ss timestamp seeking
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-vf', f"select='eq(n\\,{frame_idx})'",
            '-vsync', '0',
            '-frames:v', '1',
            '-q:v', '1',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True)

        if result.returncode != 0:
            print(f"  ⚠️ Warning: Failed to extract frame {frame_idx} at {ts:.3f}s")
            continue

        # Read and process frame immediately
        frame = cv2.imread(output_path)
        if frame is None:
            print(f"  ⚠️ Warning: Failed to read extracted frame {frame_idx} at {ts:.3f}s")
            continue

        # Detect QR codes
        qr_codes = detect_qr_fast(frame)
        assert len(qr_codes) < 2, f"Multiple QR codes detected at frame {frame_idx} (timestamp {ts:.3f}s)!"

        if len(qr_codes) > 0:
            qr_data = qr_codes[0]
            qr_frame_num = parse_qr_frame_number(qr_data, prefix)

            if qr_frame_num is not None:
                # Perfect alignment: frame at index frame_idx (timestamp ts) has QR code qr_frame_num
                video_time = ts

                if qr_frame_num not in seen_qr_frames:
                    seen_qr_frames[qr_frame_num] = []

                seen_qr_frames[qr_frame_num].append(video_time)

    shutil.rmtree(temp_dir, ignore_errors=True)
    print(f"  🧹 Cleaned up temporary frames")

    # Take mean
    video_map  = {}
    for qr_frame_num, times in seen_qr_frames.items():
        mean_time = np.mean(times)
        video_map[qr_frame_num] = mean_time
    
    # Sort by QR frame number
    sorted_qr_nums = sorted(video_map.keys())

    print(f"\n  ✅ Detected {len(video_map)} unique QR codes")
    assert len(video_map) > 0, "No QR codes detected in video segment"
    print("  QR code numbers range:", sorted_qr_nums[0], "-", sorted_qr_nums[-1])
    for k, v in list(video_map.items())[:10]:
        print(f"    {k} at {v:.2f}s")

    return video_map, video_duration


def calculate_offset_compared_to_anchor(video_map, anchor_map):
    """
    Calculate video offset compared to anchor timecode

    Args:
        video_map: Video QR code mapping [(video_time, qr_frame_num), ...]
        anchor_map: Anchor time mapping

    Returns:
        Offset statistics dictionary
    """
    offsets = []

    for qr_frame_num, video_time in video_map.items():
        if qr_frame_num not in anchor_map:
            continue
        anchor_time = anchor_map[qr_frame_num]
        offset = video_time - anchor_time
        offsets.append(offset)

    offsets = np.array(offsets)
    offset_mean = np.mean(offsets)
    offset_std = np.std(offsets)

    print(f"  Calculated offset: {offset_mean:.3f}s (std: {offset_std:.3f}s)")



    result = {
        "offset_mean": float(offset_mean),
        "offset_std": float(offset_std),
        "num_samples": len(offsets),}


    return result




def main():
    parser = argparse.ArgumentParser(
        description='Camera synchronization tool based on anchor QR code video',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=""""""
    )

    parser.add_argument('--src_tag', type=str, default= 'ori', help='subdir containing videos from multiple cameras')

    parser.add_argument('--path_anchor_video', default='../assets/qr_sync_120sec_30fps.mp4',
                       help='Anchor QR code video path (recommended, automatically extract metadata)')

    parser.add_argument('--video_scan_start_time', type=float, default=0.0,
                       help='Start time (seconds) for scanning QR codes in videos, default 0.0')
    parser.add_argument('--video_scan_duration', type=float, default=1.0,
                       help='Duration (seconds) for scanning QR codes in videos, default 120.0')

    parser.add_argument('--prefix', type=str, default='',
                       help='QR code prefix (e.g., "SYNC-"), default none')
    parser.add_argument('--step', type=int, default=2,
                       help='Frame step for scanning videos, default 2')
    

    args = parser.parse_args()

    # Check dependencies
    if not HAS_PYZBAR:
        print("⚠️ Warning: pyzbar not installed, will use OpenCV detection (slower)")
        print("   Recommended install: pip install pyzbar")

    # Load anchor metadata (priority: CSV > Video > Default)
    print("\n" + "=" * 80)
    print("Step 0: Load Anchor Metadata")
    print("=" * 80)

    anchor_map  = extract_anchor_metadata_from_video(video_path=args.path_anchor_video,  prefix=args.prefix)

    # get all MP4 files in the src_tag subdir
    src_dir = os.path.join(PATH_ASSETS_VIDEOS, args.src_tag)
    list_src_videos=glob.glob(os.path.join(src_dir,'*/*.MP4'))
    list_src_videos.sort()
    print("list_src_videos:",list_src_videos)

    print("\n" + "=" * 80)
    print("Step 1: Calculate Offsets for All Videos")
    print("=" * 80)

    # Calculate offsets and durations for all videos
    video_offsets = {}
    video_durations = {}

    for path_video in list_src_videos:
        print(f"\nProcessing: {os.path.basename(path_video)}")

        cam_tag = path_video.split('/')[-2]
        video_start_time=START_TIME_STAMP[cam_tag] if USE_START_TIME_STAMP and cam_tag in START_TIME_STAMP else args.video_scan_start_time
        # Scan QR codes in video
        cvideo_map, duration = scan_video_qr_segment(path_video, video_start_time, args.video_scan_duration, args.step, args.prefix)

        
        # Calculate offset compared to anchor
        offset_result = calculate_offset_compared_to_anchor(cvideo_map, anchor_map)
        offset = offset_result['offset_mean']
        video_offsets[path_video] = offset

        # Get video duration
        video_durations[path_video] = duration

        print(f"  Duration: {duration:.2f}s, Offset: {offset:.3f}s (std: {offset_result['offset_std']:.3f}s)")
        print("-" * 40)

    # Synchronize all videos (similar to synchronize_cameras in calib_utils.py)
    print("\n" + "=" * 80)
    print("Step 2: Synchronize Videos")
    print("=" * 80)

    # Get FPS (assume all videos have same FPS)
    fps = get_fps(list_src_videos[0])
    for i in range(1, len(list_src_videos)):
        assert fps == get_fps(list_src_videos[i]), "All videos should have the same FPS."
    #fps = round(fps)

    start_times = [-video_offsets[vp] for vp in list_src_videos]
    end_times = [start_times[i] + video_durations[list_src_videos[i]] for i in range(len(start_times))]

    # Find the synchronization window (overlap of all videos)
    max_start = max(start_times)
    min_end = min(end_times)
    sync_duration = min_end - max_start

    print(f"Sync window: {sync_duration:.2f} seconds starting at {max_start:.2f}s (relative to anchor)")

    # Create meta_info similar to synchronize_cameras output
    meta_info = {}
    for i, path_video in enumerate(list_src_videos):
        # Offset = how much to skip at the beginning of this video
        offset_to_skip = max_start - start_times[i]
        assert offset_to_skip >= 0, f"Offset should be non-negative, got {offset_to_skip:.3f}s"

        video_tag = '/'.join(path_video.split('/')[-2:])
        meta_info[video_tag] = {
            "qr_offset_to_anchor": float(video_offsets[path_video]),  # Original QR-based offset
            "src_duration": float(video_durations[path_video]),
            "offset": float(offset_to_skip),  # How much to skip at start for sync
            "duration": float(sync_duration),  # Synchronized duration
            "fps": fps
        }

    # Save meta_info to JSON
    output_json = os.path.join(src_dir, 'qr_sync_meta.json')
    with open(output_json, 'w') as f:
        json.dump(meta_info, f, indent=2)

    print(f"\n✅ Synchronization complete! Meta info saved to: {output_json}")
    print("\nSynchronization Summary:")
    for video_tag, info in meta_info.items():
        print(f"  {video_tag}:")
        print(f"    Skip first {info['offset']:.3f}s, use next {info['duration']:.2f}s")
        print(f"    (QR offset to anchor: {info['qr_offset_to_anchor']:.3f}s)")



if __name__ == '__main__':
    exit(main())
