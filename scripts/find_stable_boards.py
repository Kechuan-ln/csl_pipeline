#!/usr/bin/env python3

import cv2
import numpy as np
import tqdm
import yaml
from pathlib import Path
import argparse
from typing import Dict, List, Tuple, Optional
import glob
from tqdm import tqdm
import re
import os
import sys

# Override PATH_ASSETS_VIDEOS from environment before importing constants
os.environ['PATH_ASSETS_VIDEOS'] = os.environ.get('PATH_ASSETS_VIDEOS', '/Volumes/FastACIS/')

sys.path.append('..')  # Add parent directory to path for imports
# Don't import PATH_ASSETS_VIDEOS from constants - use environment variable directly


class CharucoBoardDetector:
    def __init__(self, config_path: str):
        """Initialize the detector with board configuration."""
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        board_config = config['common']
        self.size = tuple(board_config['size'])
        self.square_length = board_config['square_length']
        self.marker_length = board_config['marker_length']
        self.min_points = board_config.get('min_points', 40)
        
        # Create ArUco dictionary
        aruco_dict_name = board_config['aruco_dict']
        dict_map = {
            '7X7_250': cv2.aruco.DICT_7X7_250,
            '4X4_100': cv2.aruco.DICT_4X4_100,
            '5X5_100': cv2.aruco.DICT_5X5_100,
        }
        if aruco_dict_name not in dict_map:
            raise ValueError(f"Unsupported ArUco dictionary: {aruco_dict_name}")

        if hasattr(cv2.aruco, 'getPredefinedDictionary'):
            self.aruco_dict = cv2.aruco.getPredefinedDictionary(dict_map[aruco_dict_name])
        else:
            self.aruco_dict = cv2.aruco.Dictionary_get(dict_map[aruco_dict_name])

        # Create ChArUco board
        if hasattr(cv2.aruco, 'CharucoBoard') and not hasattr(cv2.aruco, 'CharucoBoard_create'):
            self.board = cv2.aruco.CharucoBoard(
                self.size, self.square_length, self.marker_length, self.aruco_dict
            )
        else:
            width, height = self.size
            self.board = cv2.aruco.CharucoBoard_create(
                width, height, self.square_length, self.marker_length, self.aruco_dict
            )

        # ArUco detection parameters
        if hasattr(cv2.aruco, 'DetectorParameters_create'):
            self.aruco_params = cv2.aruco.DetectorParameters_create()
        else:
            self.aruco_params = cv2.aruco.DetectorParameters()
            
        if 'aruco_params' in config:
            aruco_config = config['aruco_params']
            if 'adaptiveThreshWinSizeMax' in aruco_config:
                self.aruco_params.adaptiveThreshWinSizeMax = aruco_config['adaptiveThreshWinSizeMax']
            if 'adaptiveThreshWinSizeStep' in aruco_config:
                self.aruco_params.adaptiveThreshWinSizeStep = aruco_config['adaptiveThreshWinSizeStep']

    def detect_board(self, image: np.ndarray) -> Optional[Dict]:
        """Detect ChArUco board in image."""
        # Detect ArUco markers
        marker_corners, marker_ids, _ = cv2.aruco.detectMarkers(
            image, self.aruco_dict, parameters=self.aruco_params
        )
        
        if marker_ids is None:
            return None
        
        # Interpolate ChArUco corners
        _, corners, ids = cv2.aruco.interpolateCornersCharuco(
            marker_corners, marker_ids, image, self.board
        )
        
        if ids is None or len(ids) < self.min_points:
            return None
        
        return {
            'corners': corners.squeeze(1),
            'ids': ids.squeeze(1),
            'num_points': len(ids)
        }


def calculate_frame_stability(detections: List[Optional[Dict]]) -> List[float]:
    """Calculate stability scores by comparing with previous frame."""
    stability_scores = []
    
    for i in range(len(detections)):
        if detections[i] is None:
            stability_scores.append(1000)
            continue
        
        # First frame has no previous frame to compare
        if i == 0:
            stability_scores.append(1000)
            continue
            
        # Previous frame must exist and have detection
        if detections[i-1] is None:
            stability_scores.append(1000)
            continue
        
        current_corners = detections[i]['corners']
        current_ids = detections[i]['ids']
        prev_corners = detections[i-1]['corners']
        prev_ids = detections[i-1]['ids']
        
        # Find common corner points between current and previous frame
        common_ids = np.intersect1d(current_ids, prev_ids)
        if len(common_ids) < 10:  # Need sufficient common points
            stability_scores.append(1000)
            continue
        
        # Get corner positions for common IDs
        current_mask = np.isin(current_ids, common_ids)
        prev_mask = np.isin(prev_ids, common_ids)
        
        current_common = current_corners[current_mask]
        prev_common = prev_corners[prev_mask]
        
        # Sort by IDs to ensure correspondence
        current_sorted_ids = current_ids[current_mask]
        prev_sorted_ids = prev_ids[prev_mask]
        
        current_sort_idx = np.argsort(current_sorted_ids)
        prev_sort_idx = np.argsort(prev_sorted_ids)
        
        current_common = current_common[current_sort_idx]
        prev_common = prev_common[prev_sort_idx]
        
        # Calculate movement (lower is more stable)
        movements = np.linalg.norm(current_common - prev_common, axis=1)
        avg_movement = np.mean(movements)
        
        # Convert to stability score (higher is more stable)
        stability_score = avg_movement
        stability_scores.append(stability_score)
    
    return stability_scores


def downsample_consecutive_frames(indices: List[int], min_gap: int = 5) -> List[int]:
    """
    Downsample consecutive frame indices to avoid selecting too many similar frames.
    
    Args:
        indices: List of frame indices
        min_gap: Minimum gap between selected frames
        
    Returns:
        Downsampled list of indices
    """
    if not indices:
        return indices
    
    downsampled = [indices[0]]  # Always keep first frame
    
    for idx in indices[1:]:
        # Only add if it's sufficiently far from the last selected frame
        if idx - downsampled[-1] >= min_gap:
            downsampled.append(idx)
    
    return downsampled




def is_camera_folder(folder_name: str) -> bool:
    """Check if a folder name matches the camera folder pattern (cam0, cam1, etc.)"""
    camera_folder_pattern = re.compile(r'^cam\d+$')
    return camera_folder_pattern.match(folder_name) is not None

def find_stable_boards(data_dir: str, board_config_path: str,
                      movement_threshold: float = 10.0,
                      min_detection_quality: int = 40,
                      cam_filter: List[str] = None) -> Dict[str, List[int]]:
    """
    Find stable board detections across camera folders.
    
    Args:
        data_dir: Root directory containing cam1, cam2, etc. folders
        board_config_path: Path to board configuration YAML
        stability_threshold: Minimum stability score for selection
        min_detection_quality: Minimum number of detected points
        
    Returns:
        Dictionary mapping camera names to lists of stable frame indices
    """
    detector = CharucoBoardDetector(board_config_path)
    results = {}
    
    # Find all camera directories
    data_path = Path(data_dir)
    
    cam_dirs = [d for d in data_path.iterdir() if d.is_dir() and is_camera_folder(d.name)]

    # Filter cameras if specified
    if cam_filter:
        cam_dirs = [d for d in cam_dirs if d.name in cam_filter]

    if not cam_dirs:
        print(f"No camera directories found in {data_dir}")
        return results
    
    for cam_dir in sorted(cam_dirs):
        print(f"Processing {cam_dir.name}...")
        
        # Get all image files
        image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff']
        image_files = []
        for ext in image_extensions:
            found = glob.glob(str(cam_dir / ext))
            image_files.extend(found)
        
        image_files.sort()  # Ensure consistent ordering
        
        if not image_files:
            print(f"  No images found in {cam_dir}")
            continue
        
        print(f"  Found {len(image_files)} images")
        
        # Detect boards in all images
        detections = []
        for i, img_path in tqdm(enumerate(image_files), total=len(image_files)):
            
            image = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
            if image is None:
                detections.append(None)
                continue
            
            detection = detector.detect_board(image)
            
            # Filter by detection quality
            if detection and detection['num_points'] >= min_detection_quality:
                detections.append(detection)
            else:
                detections.append(None)
        
        # Calculate stability scores
        stability_scores = calculate_frame_stability(detections)
        
        # Select stable frames
        stable_indices = []
        for i, (detection, stability) in enumerate(zip(detections, stability_scores)):
            if detection is not None and stability < movement_threshold:
                cimg_idx = int(image_files[i].split('/')[-1].split('_')[-1].split('.')[0])
                print(image_files[i],cimg_idx, stability)
                stable_indices.append(cimg_idx)
        
        results[cam_dir.name] = stable_indices
        print(f"  Found {len(stable_indices)} stable boards out of {len(image_files)} images")
        
    
    return results


def main():
    parser = argparse.ArgumentParser(description='Find stable calibration board detections')
    parser.add_argument('--recording_tag', default='sync_9122/original', help='Indicate the recording folder under PATH_ASSETS_VIDEOS')
    parser.add_argument('--boards', default='../multical/asset/charuco_b1_2.yaml',
                       help='Path to board configuration file')
    parser.add_argument('--movement_threshold', type=float, default=5,
                       help='Minimum movement threshold for selection')
    parser.add_argument('--min_detection_quality', type=int, default=40,
                       help='Minimum number of detected corner points')
    parser.add_argument('--downsample_rate',default=5, type=int, help='Downsample rate for frame selection')
    parser.add_argument('--cam_filter', type=str, default=None, help='Comma-separated list of cameras to process (e.g., cam1,cam2)')
    parser.add_argument('--copy_stable_frames', action='store_true', help='Copy stable frames to output directory')
    parser.add_argument('--output_suffix', type=str, default='_stable', help='Suffix for output directory (default: _stable)')
    parser.add_argument('--max_frames_per_camera', type=int, default=500, help='Maximum frames per camera to copy (default: 500)')

    args = parser.parse_args()

    # Parse camera filter
    cam_filter = args.cam_filter.split(',') if args.cam_filter else None

    # Find stable boards - use environment variable directly
    PATH_ASSETS_VIDEOS = os.environ.get('PATH_ASSETS_VIDEOS', '/Volumes/FastACIS/')
    path_data = os.path.join(PATH_ASSETS_VIDEOS, args.recording_tag)
    results = find_stable_boards(
        path_data,
        args.boards,
        args.movement_threshold,
        args.min_detection_quality,
        cam_filter
    )

    # Downsample consecutive frames and limit per camera
    indices_set = set()
    for camera, indices in results.items():
        if indices:
            # First downsample
            indices = downsample_consecutive_frames(indices, min_gap=args.downsample_rate)
            # Then limit to max_frames_per_camera
            if len(indices) > args.max_frames_per_camera:
                indices = indices[:args.max_frames_per_camera]
            results[camera] = indices
            indices_set.update(results[camera])

    # Print results
    print("\n=== RESULTS ===")
    print(results)
    print("Total stable frames found:", len(indices_set))

    indices_set = list(indices_set)
    indices_set.sort()
    indices_set = downsample_consecutive_frames(indices_set, min_gap=args.downsample_rate)
    print("Stable frame indices:", sorted(list(indices_set)))

    # Copy stable frames if requested
    if args.copy_stable_frames:
        import shutil
        print("\n=== COPYING STABLE FRAMES ===")

        # Create output directory - use environment variable
        PATH_ASSETS_VIDEOS_LOCAL = os.environ.get('PATH_ASSETS_VIDEOS', '/Volumes/FastACIS/')
        output_tag = args.recording_tag.replace('/original', f'/original{args.output_suffix}')
        output_path = os.path.join(PATH_ASSETS_VIDEOS_LOCAL, output_tag)

        print(f"Output directory: {output_path}")

        # Use union of all stable frame indices for all cameras
        # so that every camera directory has the same filenames
        # (multical requires matching filenames across cameras)
        union_indices = sorted(indices_set)

        total_copied = 0
        for camera in results.keys():
            # Create camera output directory
            cam_output_dir = os.path.join(output_path, camera)
            os.makedirs(cam_output_dir, exist_ok=True)

            # Copy union frames from this camera's original directory
            cam_input_dir = os.path.join(path_data, camera)
            cam_copied = 0

            for frame_idx in union_indices:
                src_file = os.path.join(cam_input_dir, f"frame_{frame_idx:04d}.jpg")
                if os.path.exists(src_file):
                    dst_file = os.path.join(cam_output_dir, f"frame_{frame_idx:04d}.jpg")
                    shutil.copy2(src_file, dst_file)
                    total_copied += 1
                    cam_copied += 1

            print(f"[{camera}] Copied {cam_copied}/{len(union_indices)} frames")

        print(f"\n✓ Total frames copied: {total_copied}")
        print(f"✓ Output: {output_path}")

        # Save frame indices to JSON
        import json
        json_path = os.path.join(output_path, 'stable_frame_indices.json')
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"✓ Frame indices saved to: {json_path}")


if __name__ == '__main__':
    main()