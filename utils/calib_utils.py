import os
import glob
from tqdm import tqdm
import numpy as np
import cv2
import subprocess
import re
import json
try:
    import av
except ImportError:
    pass

np.set_printoptions(precision=6, suppress=True)


def extract_framewise_timestamps_av(video_path, ss=None, duration=None):
    container = av.open(video_path)
    stream = container.streams.video[0]
    
    time_base = stream.time_base
    print(f"Video time base: {time_base}")
    timestamps = []
    
    for packet in container.demux(stream):
        for frame in packet.decode():
            # 正確なタイムスタンプ（秒）
            ts = float(frame.pts * time_base)
            timestamps.append(ts)
    
    if ss is not None:
        end_time = ss + duration if duration else float('inf')
        timestamps = [ts for ts in timestamps if ss <= ts < end_time]
    print(f"  ✅ Extracted {len(timestamps)} frame timestamps")
    return timestamps

def extract_framewise_timestamps(video_path, ss=None, duration=None):
    """
    Extract frame timestamps using ffprobe

    Args:
        video_path: Path to video file
        ss: Start time in seconds (optional, filters to frames starting at this time)
        duration: Duration in seconds (optional, filters frames within this duration from ss)

    Returns:
        List of absolute timestamps in seconds for each frame (filtered if ss/duration specified)
    """
    # Extract ALL timestamps from entire video (preserves absolute pts_time)
    # Don't use -ss/-t as they cause timestamps to reset to 0
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'frame=pts_time',
        '-of', 'csv=p=0',
        video_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    timestamps = []
    for line in result.stdout.strip().split('\n'):
        if line:
            # strip ',' if present
            line = line.strip().rstrip(',')
            timestamps.append(float(line))

    # Filter to time range [ss, ss+duration) if specified
    # This preserves absolute timestamps, just filters them
    if ss is not None:
        end_time = ss + duration if duration else float('inf')
        timestamps = [ts for ts in timestamps if ss <= ts < end_time]

    print(f"  ✅ Extracted {len(timestamps)} frame timestamps")
    return timestamps



def extract_timecode(video_path):
    # Command to extract timecode using ffprobe
    command = [
        "ffprobe",
        "-v", "error",                  # Suppress unnecessary output
        "-select_streams", "v:0",       # Select the first video stream
        "-show_entries", "stream_tags=timecode",  # Show timecode from tags
        "-of", "default=noprint_wrappers=1:nokey=1",  # Clean output
        video_path
    ]
    
    # Run the command
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # The timecode should be in the standard output
    timecode = result.stdout.strip()
    if timecode:
        return timecode
    else:
        return "Timecode not found."


def get_video_length(video_path):
    # Run ffprobe and capture the output
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    
    # Extract the duration from the output
    duration = float(result.stdout.strip())
    return duration


def get_fps(video_path):
    # Run ffprobe command
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Extract and calculate FPS
    fps_fraction = result.stdout.strip()
    num, denom = map(int, fps_fraction.split('/'))
    fps = num / denom
    
    return fps

def timecode_to_seconds(tc, fps):
    hours, minutes, seconds, frames = map(int, re.split('[:;]', tc))
    return hours*3600 + minutes*60 + seconds + frames/fps  



def synchronize_cameras(list_src_videos):
    timecodes = [extract_timecode(vp) for vp in list_src_videos]
    assert not (None in timecodes), "Some videos do not have timecodes."
    durations = [get_video_length(vp) for vp in list_src_videos]


    fps = get_fps(list_src_videos[0])
    for i in range(1, len(list_src_videos)):
        assert fps == get_fps(list_src_videos[i]), f"All videos should have the same FPS, but got {fps} and {get_fps(list_src_videos[i])} for {list_src_videos[i]}."
    
    fps = round(fps)

    # Convert timecodes to seconds
    start_times = [timecode_to_seconds(tc, fps=fps) for tc in timecodes]
    end_times = [start_times[i] + durations[i] for i in range(len(start_times))]

    # Find the maximum start time, as we'll sync all videos to this point
    max_start = max(start_times)
    min_end = min(end_times)
    duration = min_end - max_start
    
    print(f"Sync window: {duration:.2f} seconds starting at {max_start:.2f}s")

    meta_info = {}
    for i, path_video in enumerate(list_src_videos):
        offset = max_start - start_times[i]
        assert offset >= 0, "The offset should be positive."

        video_tag = '/'.join(path_video.split('/')[-2:])
        meta_info[video_tag] = {"src_timecode": timecodes[i],"src_duration": durations[i],"offset": offset,"duration": duration,"fps": fps}

    return meta_info


def undistort_cameras_from_json(path_intr):
    with open(path_intr, 'r') as f:
        json_intrinsics = json.load(f)
    
    # Create undistorted intrinsics
    json_intrinsics_undist = json.loads(json.dumps(json_intrinsics))
    for cam_key in json_intrinsics['cameras']:
        w, h = json_intrinsics['cameras'][cam_key]['image_size']
        K = np.array(json_intrinsics['cameras'][cam_key]['K'], dtype=np.float32)
        dist = np.array(json_intrinsics['cameras'][cam_key]['dist'], dtype=np.float32).flatten()
        
        new_K, roi = cv2.getOptimalNewCameraMatrix(K, dist, (w, h), 1, (w, h))
        
        json_intrinsics_undist['cameras'][cam_key]['K'] = new_K.tolist()
        json_intrinsics_undist['cameras'][cam_key]['dist'] = [[0.0, 0.0, 0.0, 0.0, 0.0]]
    
    
    # Save undistorted intrinsics
    path_intr_undist = path_intr.replace('.json', '_undistorted.json')
    with open(path_intr_undist, 'w') as f:
        json.dump(json_intrinsics_undist, f, indent=2)
        
    return json_intrinsics, json_intrinsics_undist