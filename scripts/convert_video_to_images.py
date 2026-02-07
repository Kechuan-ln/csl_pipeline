import os
import argparse
import glob
import cv2
from tqdm import tqdm

import sys
# Ensure new_calibration_code is in path first, before parent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import shutil
import numpy as np
np.set_printoptions(precision=6, suppress=True)

from utils.io_utils import convert_video_to_images
from utils.calib_utils import undistort_cameras_from_json
from utils.constants import IMG_FORMAT_IO

# Override PATH_ASSETS_VIDEOS if environment variable is set
PATH_ASSETS_VIDEOS = os.environ.get('PATH_ASSETS_VIDEOS', '../assets/videos/')

def process_video_folder(src_dir, target_dir, list_cam_tags, fps, duration, ss, path_intr=None, image_format='png', quality=2):
    if path_intr is not None:
        json_intrinsics, json_intrinsics_nodist = undistort_cameras_from_json(path_intr)
    else:
        json_intrinsics, json_intrinsics_nodist = None, None

    for cam_tag in list_cam_tags:
        cam_path = os.path.join(src_dir, cam_tag)
        print(f"\n[{cam_tag}] Checking camera path: {cam_path}")
        print(f"[{cam_tag}] Path exists: {os.path.exists(cam_path)}")

        mp4_files = glob.glob(os.path.join(cam_path, "*.MP4"))
        print(f"[{cam_tag}] Found {len(mp4_files)} MP4 files")

        for path_video in mp4_files:
            video_name = os.path.splitext(os.path.basename(path_video))[0]
            if len(mp4_files)> 1:
                dir_images = os.path.join(target_dir, "original", cam_tag, video_name)
            else:
                dir_images = os.path.join(target_dir, "original", cam_tag)
            if os.path.exists(dir_images):
                # If the directory exists, remove it to avoid mixing old and new images
                shutil.rmtree(dir_images)

            os.makedirs(dir_images, exist_ok=True)

            print(f"Converting {path_video} to images in {dir_images} at {fps} fps (format: {image_format})")
            # Use local io_utils function with image_format parameter
            convert_video_to_images(path_video, dir_images, fps=fps, duration=duration, ss=ss, image_format=image_format)

            if json_intrinsics is None:
                continue

            # Undistort images if intrinsics are provided
            if len(mp4_files) > 1:
                dir_output = os.path.join(target_dir, "undistorted", cam_tag, video_name)
            else:
                dir_output = os.path.join(target_dir, "undistorted", cam_tag)
            if os.path.exists(dir_output):
                shutil.rmtree(dir_output)
            os.makedirs(dir_output, exist_ok=True)

            # Find image files based on extracted format
            image_files = glob.glob(os.path.join(dir_images, f"*.{image_format}"))
            image_files.sort()
            ori_K = np.array(json_intrinsics['cameras'][cam_tag]['K'], dtype=np.float32)
            ori_dist = np.array(json_intrinsics['cameras'][cam_tag]['dist'], dtype=np.float32).flatten()

            new_K = np.array(json_intrinsics_nodist['cameras'][cam_tag]['K'], dtype=np.float32)

            for image_path in tqdm(image_files):
                img = cv2.imread(image_path)
                undistorted_img = cv2.undistort(img, ori_K, ori_dist, None, new_K)

                path_output = os.path.join(dir_output, os.path.basename(image_path))
                cv2.imwrite(path_output, undistorted_img)


def main():
    parser = argparse.ArgumentParser(description="Convert MP4 videos to images")
    parser.add_argument("--src_tag", default='intr_09121',  help="Source directory containing camera folders, under PATH_ASSETS_VIDEOS")
    parser.add_argument("--cam_tags", default="cam01,cam02,cam03", help="Comma-separated list of camera tags to process")
    parser.add_argument("--fps", type=float, required=True, help="Frames per second for extraction")
    parser.add_argument("--duration", type=str, default=None, help="Duration in seconds to extract from the video (optional)")
    parser.add_argument("--ss", type=str, default=None, help="Offset to start extracting from the video (optional)")
    parser.add_argument("--path_intr", help="Path to intrinsics.json file for undistortion (optional), if provided, under PATH_ASSETS_VIDEOS")
    parser.add_argument("--format", default="png", choices=["png", "jpg", "jpeg"], help="Output image format (default: png)")
    parser.add_argument("--quality", type=int, default=2, help="JPEG quality (2-31, lower is better, only for jpg), default: 2")

    args = parser.parse_args()

    print(f"PATH_ASSETS_VIDEOS: {PATH_ASSETS_VIDEOS}")
    src_dir = os.path.join(PATH_ASSETS_VIDEOS, args.src_tag)
    print(f"Source directory: {src_dir}")
    print(f"Checking if source directory exists: {os.path.exists(src_dir)}")

    cam_tags = args.cam_tags.split(',')
    print(f"Processing {len(cam_tags)} cameras: {cam_tags}")

    if args.path_intr is not None:
        args.path_intr = os.path.join(PATH_ASSETS_VIDEOS, args.path_intr)
        assert os.path.exists(args.path_intr), f"Intrinsics file does not exist: {args.path_intr}"
    process_video_folder(src_dir, src_dir, cam_tags, args.fps, args.duration, args.ss, args.path_intr,
                        image_format=args.format, quality=args.quality)


if __name__ == "__main__":
    main()
