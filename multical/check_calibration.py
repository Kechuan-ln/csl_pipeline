"""
Check calibration by visualizing reprojections and calculating RMS errors.

This script takes:
1. Images
2. Calibration JSON from calibrate.py (contains board2base transforms)
3. A second JSON with intrinsics and extrinsics (base2cam)

It will:
- Detect charuco board corners in images
- Use board2base from first JSON and intrinsics/base2cam from second JSON
- Reproject the board corners
- Visualize detected vs reprojected points
- Calculate and report RMS errors
"""

import numpy as np
import cv2
import json
import os
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import sys

import glob

from multical.board import load_config
from multical.config import *

# Override PATH_ASSETS_VIDEOS from environment variable before importing constants
os.environ['PATH_ASSETS_VIDEOS'] = os.environ.get('PATH_ASSETS_VIDEOS', '/Volumes/FastACIS/')
os.environ['PATH_ASSETS'] = os.environ.get('PATH_ASSETS', '/Volumes/FastACIS/')

sys.path.append('..')
from utils.constants import PATH_ASSETS, PATH_ASSETS_VIDEOS, IMG_FORMAT
from utils.logger import ColorLogger


def create_transform_matrix(R, T):
    """Create 4x4 transformation matrix from R (3x3) and T (3x1 or 3,)"""
    transform = np.eye(4)
    transform[:3, :3] = np.array(R)
    transform[:3, 3] = np.array(T).flatten()
    return transform


def decompose_transform_matrix(transform):
    """Decompose 4x4 transformation matrix into R (3x3) and T (3x1)"""
    R = transform[:3, :3]
    T = transform[:3, 3].reshape(3, 1)
    return R, T


def load_json_file(filepath):
    """Load JSON file"""
    with open(filepath, 'r') as f:
        return json.load(f)


def get_board_3d_points(board):
    """Get 3D points of charuco board in board coordinate system"""
    # For charuco board, the board.points property gives the 3D coordinates
    return board.points


def reproject_points(points_3d, rvec, tvec, K, dist):
    """Reproject 3D points to 2D image plane"""
    points_2d, _ = cv2.projectPoints(points_3d, rvec, tvec, K, dist)
    return points_2d.squeeze()


def calculate_rms_error(detected_points, reprojected_points):
    """Calculate RMS error between detected and reprojected points"""
    diff = detected_points - reprojected_points
    squared_distances = np.sum(diff ** 2, axis=1)
    rms = np.sqrt(np.mean(squared_distances))
    return rms, squared_distances


def draw_axis(img, rvec, tvec, K, dist, square_length):
    """
    Draw coordinate frame axes (matching calibrate.py implementation)

    Args:
        img: Input image
        rvec: Rotation vector
        tvec: Translation vector
        K: Camera intrinsic matrix
        dist: Distortion coefficients
        square_length: Length of one square on the board
    """
    n_squares = 3
    axis = np.float32([[n_squares*square_length, 0, 0],
                       [0, n_squares*square_length, 0],
                       [0, 0, n_squares*square_length],
                       [0, 0, 0]]).reshape(-1, 3)
    imgpts, jac = cv2.projectPoints(axis, rvec, tvec, K, dist)

    try:
        colors = {'ox': (0, 0, 255), 'oy': (0, 255, 0), 'oz': (255, 0, 0)}
        cv2.drawFrameAxes(img, K, dist, rvec, tvec, n_squares*square_length, thickness=1)
        cv2.putText(img, 'X', tuple(imgpts[0].ravel().astype(int)),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, colors['ox'], 2)
        cv2.putText(img, 'Y', tuple(imgpts[1].ravel().astype(int)),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, colors['oy'], 2)
        cv2.putText(img, 'Z', tuple(imgpts[2].ravel().astype(int)),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, colors['oz'], 2)
    except Exception as e:
        pass
    return img


def visualize_detection_and_reprojection(image, detection, rvec, tvec, K, dist, square_length,
                                         reprojected_points=None, detected_ids=None):
    """
    Visualize detected charuco corners and coordinate frame (matching calibrate.py style)

    Args:
        image: Input image
        detection: Detection result from board.detect()
        rvec: Rotation vector for drawing axes
        tvec: Translation vector for drawing axes
        K: Camera intrinsic matrix
        dist: Distortion coefficients
        square_length: Board square length
        reprojected_points: Optional reprojected points for comparison
        detected_ids: Optional detected IDs
    """
    vis_image = image.copy()

    # Draw detected charuco corners (yellow) - matching calibrate.py:119
    try:
        if detection.ids is not None and len(detection.ids) > 0:
            cv2.aruco.drawDetectedCornersCharuco(vis_image,
                                                detection.corners[:, np.newaxis],
                                                detection.ids[:, np.newaxis],
                                                (0, 255, 255))
    except Exception as e:
        pass  # Silently ignore drawing errors

    # Draw coordinate frame axes - matching calibrate.py:149
    vis_image = draw_axis(vis_image, rvec, tvec, K, dist, square_length)

    # Optionally draw reprojected points for comparison
    if reprojected_points is not None and detected_ids is not None:
        # Match reprojected points with detected IDs
        for i, corner_id in enumerate(detected_ids):
            if corner_id < len(reprojected_points):
                reproj_pt = tuple(reprojected_points[corner_id].astype(int))
                # Draw reprojected points in red
                cv2.circle(vis_image, reproj_pt, 4, (0, 0, 255), 2)

    return vis_image


@dataclass
class CheckCalibration:
    """Check calibration accuracy"""
    image_path: str                          # Path to images or image directory (relative to PATH_ASSETS_VIDEOS)
    reference_json: str                      # Path to reference JSON with intrinsics and base2cam
    board_config: str                        # Path to board configuration YAML
    min_points: int = 0                    # Minimum points for detection
    verbose: bool = False                    # Enable verbose output

    def execute(self):
        """Execute calibration check"""
        # Force PATH_ASSETS_VIDEOS to use environment variable or default
        PATH_ASSETS_VIDEOS_ACTUAL = os.environ.get('PATH_ASSETS_VIDEOS', '/Volumes/FastACIS/')

        # Resolve paths using PATH_ASSETS_VIDEOS (matching calibrate.py:27-32)
        self.image_path = os.path.join(PATH_ASSETS_VIDEOS_ACTUAL, self.image_path)
        self.calibration_json = os.path.join(self.image_path,'calibration.json')
        self.reference_json = os.path.join(PATH_ASSETS_VIDEOS_ACTUAL, self.reference_json)

        # Setup output directory first (matching calibrate.py:106-108)
        tag_path_image = self.image_path.strip('/').split('/')[-1]
        tag_reference_json = self.reference_json.strip('/').split('/')[-2]
        self.output_path = os.path.join(self.image_path, '..', 'vis', tag_path_image+'_ref_'+tag_reference_json)

        # Setup logging using utils/logger.py
        self.logger = ColorLogger(self.output_path, log_name='check_calibration.log')

        self.logger.info(f"Output directory: {self.output_path}")
        self.logger.info(f"\nLoading calibration JSON: {self.calibration_json}")
        calib_data = load_json_file(self.calibration_json)

        self.logger.info(f"Loading reference JSON: {self.reference_json}")
        ref_data = load_json_file(self.reference_json)

        self.logger.info(f"Loading board configuration: {self.board_config}")
        boards = load_config(self.board_config)

        # Get the first board (assuming single board setup)
        board_name, board = list(boards.items())[0]
        self.logger.info(f"Using board: {board_name}")
        self.logger.info(f"Board configuration: {board}")

        if self.min_points > 0:
            board.min_points = self.min_points

        # Get board 3D points
        board_3d_points = get_board_3d_points(board)
        self.logger.info(f"Board has {len(board_3d_points)} corner points")

        # Process images
        self.process_images(board, board_3d_points, calib_data, ref_data)


    def find_base2cam_key(self, cam_tag, base2cam_dict):
        """Find base2cam key for camera (matching calibrate.py:127-135)"""
        if cam_tag in base2cam_dict:
            return cam_tag

        # Try with underscore prefix
        for key in base2cam_dict.keys():
            if key.startswith(f'{cam_tag}_'):
                return key

        return None

    def process_images(self, board, board_3d_points, calib_data, ref_data):
        """Process images and check calibration"""

        # get frame_idx and calib_data mapping
        original_mapping = calib_data['image_sets']['rgb']
        name_to_idx = {}
        for idx, frame_info in enumerate(original_mapping):
            for k, v in frame_info.items():
                frame_name = v.split('/')[-1]
                name_to_idx[frame_name] = idx
                break


        image_dir = self.image_path

        # Find camera directories (direct subdirectories containing images)
        # Expected structure: image_path/camera/images.jpg
        image_files = []


        # Find all direct subdirectories (camera folders)
        # keep subdirs starts from 'cam'
        subdirs = [d for d in os.listdir(image_dir)
                    if os.path.isdir(os.path.join(image_dir, d)) and d.startswith('cam')]

        for camera_name in sorted(subdirs):
            camera_path = os.path.join(image_dir, camera_name)
            # Find images in this camera folder
            img_suffix = IMG_FORMAT.split('.')[-1]
            camera_images = glob.glob(os.path.join(camera_path, f'*.{img_suffix}'))
            camera_images.sort()
            image_files.extend(camera_images)

        self.logger.info(f"Found {len(image_files)} images across {len(subdirs)} cameras.")

        # Statistics - track per camera
        camera_rms_errors = {cam: [] for cam in subdirs}
        all_rms_errors = []
        successful_frames = 0
        camera_successful_frames = {cam: 0 for cam in subdirs}

        # Process each image
        for frame_idx, image_file in enumerate(image_files):
            image_name = os.path.basename(image_file)

            # Get camera tag from path (matching calibrate.py:103)
            cam_tag = image_file.split('/')[-2]

            camera_info = ref_data['cameras'][cam_tag]
            K = np.array(camera_info['K']).reshape(3, 3)
            dist = np.array(camera_info['dist']).flatten()

            # Get base2cam for this camera (matching calibrate.py:127-135)
            base2cam_key = self.find_base2cam_key(cam_tag, ref_data['camera_base2cam'])
            base2cam_data = ref_data['camera_base2cam'][base2cam_key]
            base2cam_mat = create_transform_matrix(base2cam_data['R'], base2cam_data['T'])

            # Load image
            image = cv2.imread(image_file)
            # Detect board
            detection = board.detect(image)                       
            detected_corners = detection.corners
            detected_ids = detection.ids
            
            # Get board2base from calibration JSON (matching calibrate.py:124-126)
            frame_key = str(name_to_idx[image_name])

            world2base_data = calib_data['camera_world2base'][frame_key]
            world2base_mat = create_transform_matrix(world2base_data['R'], world2base_data['T'])

            # Compute world2cam = base2cam @ world2base (matching calibrate.py:141-146)
            world2cam_mat = base2cam_mat @ world2base_mat
            R_world2cam, T_world2cam = decompose_transform_matrix(world2cam_mat)
            rvec_world2cam, _ = cv2.Rodrigues(R_world2cam)

            # Reproject all board points
            all_reprojected = reproject_points(board_3d_points, rvec_world2cam, T_world2cam, K, dist)

            matched_detected = []
            matched_reprojected = []
            if not (detected_ids is None or len(detected_ids) == 0):
                # Match detected IDs with board points
                # detected_ids contains the indices of detected corners

                for i, corner_id in enumerate(detected_ids):
                    if corner_id < len(board_3d_points):
                        matched_detected.append(detected_corners[i])
                        matched_reprojected.append(all_reprojected[corner_id])

                matched_detected = np.array(matched_detected)
                matched_reprojected = np.array(matched_reprojected)

                if len(matched_detected) > 0:
                    # Calculate RMS error
                    rms_error, squared_distances = calculate_rms_error(matched_detected, matched_reprojected)
                    all_rms_errors.append(rms_error)
                    camera_rms_errors[cam_tag].append(rms_error)
                    successful_frames += 1
                    camera_successful_frames[cam_tag] += 1

            # Visualize using calibrate.py style (with axes and charuco corners)
            rel_path = os.path.relpath(image_file, image_dir)
            if len(matched_detected) > 0:
                self.logger.info(f"Frame {rel_path}, Detected: {len(matched_detected)}, RMS Error: {rms_error:.2f} px")

            if self.verbose:
                vis_image = visualize_detection_and_reprojection(
                    image, detection, rvec_world2cam, T_world2cam, K, dist,
                    board.square_length, all_reprojected, detected_ids
                )

                # Add text overlay
                text_y = 50
                cv2.putText(vis_image, f"Frame {frame_idx}: {rel_path}",
                        (10, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,0, 255), 3)

                if len(matched_detected) > 0:
                    text_y += 50
                    cv2.putText(vis_image, f"RMS Error: {rms_error:.4f} px",
                            (10, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,0, 255), 3)
                    text_y += 50
                    cv2.putText(vis_image, f"Detected: {len(matched_detected)} corners",
                            (10, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,0, 255), 3)


                output_file = os.path.join(self.output_path, rel_path)
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                cv2.imwrite(output_file, vis_image)
                
        # Print summary
        self.logger.info("\n" + "="*60)
        self.logger.info("SUMMARY")
        self.logger.info("="*60)
        self.logger.info(f"Total frames processed: {len(image_files)}")
        self.logger.info(f"Successful frames: {successful_frames}")

        # Per-camera statistics
        self.logger.info("\n" + "-"*60)
        self.logger.info("PER-CAMERA STATISTICS")
        self.logger.info("-"*60)
        for cam_tag in sorted(subdirs):
            cam_errors = camera_rms_errors[cam_tag]
            cam_success = camera_successful_frames[cam_tag]
            self.logger.info(f"\n{cam_tag}:")
            self.logger.info(f"  Successful frames: {cam_success}")
            if len(cam_errors) > 0:
                mean_err = np.mean(cam_errors)
                q25 = np.percentile(cam_errors, 25)
                q50 = np.percentile(cam_errors, 50)
                q75 = np.percentile(cam_errors, 75)
                q100 = np.percentile(cam_errors, 100)
                self.logger.info(f"  Mean:      {mean_err:.4f} pixels")
                self.logger.info(f"  Quantiles: [{q25:.2f}, {q50:.2f}, {q75:.2f}, {q100:.2f}] pixels")

        # Overall statistics
        self.logger.info("\n" + "-"*60)
        self.logger.info("OVERALL STATISTICS")
        self.logger.info("-"*60)
        if len(all_rms_errors) > 0:
            self.logger.info(f"Mean:      {np.mean(all_rms_errors):.4f} pixels")
            quantile_25 = np.percentile(all_rms_errors, 25)
            quantile_50 = np.percentile(all_rms_errors, 50)
            quantile_75 = np.percentile(all_rms_errors, 75)
            quantile_100 = np.percentile(all_rms_errors, 100)
            self.logger.info(f"Quantiles: [{quantile_25:.2f}, {quantile_50:.2f}, {quantile_75:.2f}, {quantile_100:.2f}] pixels")
        self.logger.info("="*60)


def main():
    parser = argparse.ArgumentParser(
        description='Check calibration by comparing detections with reprojections',
        formatter_class=argparse.RawDescriptionHelpFormatter,)
    
    parser.add_argument('--image_path', type=str, required=True,
                       help='Path to directory containing camera folders with images (relative to PATH_ASSETS_VIDEOS or absolute)')
    parser.add_argument('--reference_json', type=str, required=True,
                       help='Path to reference JSON with camera intrinsics and base2cam extrinsics')
    parser.add_argument('--boards', type=str, required=True,
                       help='Path to board configuration YAML file')
    parser.add_argument('--min_points', type=int, default=0,
                       help='Minimum number of points for valid detection (default: 20)')
    parser.add_argument('--vis', action='store_true',
                       help='Enable visualization of detections and reprojections')

    args = parser.parse_args()

    checker = CheckCalibration(
        image_path=args.image_path,
        reference_json=args.reference_json,
        board_config=args.boards,
        min_points=args.min_points,
        verbose=args.vis,
    )

    checker.execute()


if __name__ == '__main__':
    main()
