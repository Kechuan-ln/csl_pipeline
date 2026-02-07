#!/usr/bin/env python3


import cv2
import qrcode
import numpy as np
import argparse
import os
import shutil
import subprocess
from typing import Tuple

import sys
sys.path.append('..')
from utils.constants import PATH_ASSETS, IMG_FORMAT_IO
from utils.io_utils import convert_video_to_images

def generate_qr_frame(frame_number: int, resolution: Tuple[int, int],
                     qr_size: int = 800, prefix: str = "") -> np.ndarray:
    """
    Generate a single frame QR code image

    Args:
        frame_number: Frame number
        resolution: Output resolution (width, height)
        qr_size: QR code size (pixels)
        prefix: QR code data prefix (optional, e.g., "SYNC-")

    Returns:
        RGB image (height, width, 3)
    """
    # Generate QR code data: 6 digits is sufficient for 99 minutes@60fps (approximately 360,000 frames)
    qr_data = f"{prefix}{frame_number:06d}"

    # Create QR code
    qr = qrcode.QRCode(
        version=1,  # Automatically select minimum version
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction capability
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    # Generate PIL image and convert to numpy array
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_array = np.array(qr_img.convert('RGB'))

    # Resize QR code
    qr_resized = cv2.resize(qr_array, (qr_size, qr_size),
                           interpolation=cv2.INTER_NEAREST)

    # Create black background
    frame = np.zeros((resolution[1], resolution[0], 3), dtype=np.uint8)

    # Center QR code placement
    y_offset = (resolution[1] - qr_size) // 2
    x_offset = (resolution[0] - qr_size) // 2

    # Ensure within bounds
    if y_offset >= 0 and x_offset >= 0:
        frame[y_offset:y_offset+qr_size, x_offset:x_offset+qr_size] = qr_resized
    else:
        print(f"Warning: QR code size ({qr_size}) exceeds video resolution {resolution}")
        # Scale QR code to fit
        scale = min(resolution[0], resolution[1]) * 0.8
        qr_resized = cv2.resize(qr_array, (int(scale), int(scale)),
                               interpolation=cv2.INTER_NEAREST)
        y_offset = (resolution[1] - int(scale)) // 2
        x_offset = (resolution[0] - int(scale)) // 2
        frame[y_offset:y_offset+int(scale), x_offset:x_offset+int(scale)] = qr_resized

    # Add text annotations (frame number and timestamp)
    font = cv2.FONT_HERSHEY_SIMPLEX
    time_sec = frame_number / 30.0  # Assume 30fps

    # Top: frame number
    text_frame = f"Frame: {frame_number:06d}"
    cv2.putText(frame, text_frame, (50, 80),
               font, 2.5, (255, 255, 255), 4, cv2.LINE_AA)

    # Bottom: timestamp
    text_time = f"Time: {time_sec:.2f}s"
    cv2.putText(frame, text_time, (50, resolution[1] - 50),
               font, 2.0, (255, 255, 255), 3, cv2.LINE_AA)

    return frame


def generate_qr_sync_video(output_path: str,
                           duration_seconds: int = 60,
                           fps: int = 30,
                           resolution: Tuple[int, int] = (1920, 1080),
                           qr_size: int = 800,
                           prefix: str = "",
                           verbose: bool = False) -> bool:
    """
    Generate QR code synchronization video

    Args:
        output_path: Output video path (supports .mp4, .avi, etc.)
        duration_seconds: Video duration (seconds)
        fps: Frame rate
        resolution: Resolution (width, height)
        qr_size: QR code size (pixels)
        prefix: QR code data prefix
        codec: Video codec ('mp4v' for mp4, 'XVID' for avi)

    Returns:
        Whether successful
    """
    print("=" * 80)
    print(f"Generate QR Code Sync Video")
    print("=" * 80)
    print(f"Output path: {output_path}")
    print(f"Duration: {duration_seconds} seconds")
    print(f"Frame rate: {fps} fps")
    print(f"Resolution: {resolution[0]}x{resolution[1]}")
    print(f"QR code size: {qr_size}px")
    print(f"QR code prefix: '{prefix}' (leave empty for pure numbers)")
    print("=" * 80)

    total_frames = duration_seconds * fps

    # Select encoder based on file extension
    #ext = os.path.splitext(output_path)[1].lower()
    #if ext == '.avi' and codec == 'mp4v':
    #    codec = 'XVID'
    #    print(f"Detected .avi format, automatically switching encoder to: {codec}")

    #fourcc = cv2.VideoWriter_fourcc(*codec)
    #temp_path = output_path.replace(ext, f'_temp{ext}')

    #out = cv2.VideoWriter(temp_path, fourcc, fps, resolution)
    # images dir for temporary storage, assuming current working directory
    dir_tmp = os.path.join(PATH_ASSETS, "images")
    os.makedirs(dir_tmp, exist_ok=True)

    #if not out.isOpened():
    #    print(f"❌ Unable to create video writer, please check encoder: {codec}")
    #    return False

    print(f"\nStart generating {total_frames} frames...")

    for frame_num in range(total_frames):
        frame = generate_qr_frame(frame_num, resolution, qr_size, prefix)
        cv2.imwrite(os.path.join(dir_tmp, f"frame_{frame_num:06d}.png"), frame)
        #out.write(frame)

        if (frame_num + 1) % (fps * 10) == 0:  # Report every 10 seconds
            progress = (frame_num + 1) / total_frames * 100
            print(f"  Progress: {frame_num + 1}/{total_frames} ({progress:.1f}%)")

    #out.release()
    #print(f"\n✅ Initial video generation complete")

    # Use ffmpeg to re-encode, ensuring compatibility
    print(f"\nGenerate high-quality video...")

    # Construct ffmpeg command
    cmd = [
        'ffmpeg',
        '-y',  # Overwrite output file if exists
        '-framerate', str(fps),
        '-i', os.path.join(dir_tmp, 'frame_%06d.png'),
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-crf', '18',  # High quality
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    shutil.rmtree(dir_tmp)
    print(f"✅ Final video generation complete: {output_path}")

    # Display file size
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"File size: {file_size_mb:.2f} MB")

    if verbose:
        # decompose to images for verification
        print(f"\nDecomposing video to images for verification...")
        dir_tmp = output_path.replace('.mp4','_images')
        os.makedirs(dir_tmp, exist_ok=True)
        convert_video_to_images(path_video=output_path, dir_images=dir_tmp, img_format=IMG_FORMAT_IO, fps=30)


    return True

def main():
    parser = argparse.ArgumentParser(
        description='Generate QR code sync video with a unique frame number QR code in each frame',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        Examples:
        # Generate a 60-second, 30fps QR code video (1920x1080)
        python generate_qr_sync_video.py --output qr_sync.mp4 --duration 60 --fps 30

        # Generate a 120-second, 60fps high-resolution QR code video
        python generate_qr_sync_video.py --output qr_sync_60fps.mp4 --duration 120 --fps 60 --resolution 3840x2160

        # Generate QR codes with prefix (e.g., "SYNC-000001")
        python generate_qr_sync_video.py --output qr_sync.mp4 --duration 60 --prefix "SYNC-"

        # Generate AVI format
        python generate_qr_sync_video.py --output qr_sync.avi --duration 60
        """
    )

    parser.add_argument('--duration', type=int, default=60,
                       help='Video duration (seconds), default 60 seconds')
    parser.add_argument('--fps', type=int, default=30,
                       help='Frame rate, default 30fps')
    parser.add_argument('--resolution', type=str, default='1920x1080',
                       help='Resolution, format: WIDTHxHEIGHT, default 1920x1080')
    parser.add_argument('--qr-size', type=int, default=800,
                       help='QR code size (pixels), default 800')
    parser.add_argument('--prefix', type=str, default='',
                       help='QR code data prefix (optional), e.g., "SYNC-"')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')

    args = parser.parse_args()

    # Parse resolution
    try:
        width, height = map(int, args.resolution.split('x'))
        resolution = (width, height)
    except:
        print(f"❌ Invalid resolution format: {args.resolution}")
        print("   Please use format: WIDTHxHEIGHT (e.g., 1920x1080)")
        return 1


    # Generate video
    output_path = os.path.join(PATH_ASSETS,f"qr_sync_{args.fps}fps_{args.duration}sec.mp4")
    generate_qr_sync_video(
        output_path=output_path,
        duration_seconds=args.duration,
        fps=args.fps,
        resolution=resolution,
        qr_size=args.qr_size,
        prefix=args.prefix,
        verbose=args.verbose,
    )



if __name__ == "__main__":
    exit(main())
