#!/usr/bin/env python3
"""
World to Camera Transformation Calculator

This tool computes the world to camera transformation by:
1. Loading 2D-3D point correspondences from tool_calibration.py output
2. Computing world2base (board to camera) transformation using cv2.solvePnP
3. Loading base2cam transformation from calibration.json
4. Combining transformations to get final world2cam transformation

Usage:
    python calculate_world2cam.py --points board2base_points.json --calibration calibration.json --camera cam1
"""

import os
import sys
sys.path.append('..')  # Add parent directory to path for imports
import argparse
import json
import numpy as np
import cv2

from utils.io_utils import NumpyEncoder
from dataset.recording import Recording

from utils.constants import PATH_ASSETS_VIDEOS
from utils.logger import ColorLogger


def get_args_parser():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Calculate World to Camera Transformation',
        add_help=True,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument('--path_points', type=str, required=True,
                       help='Path to 2D-3D point correspondences JSON file')
    parser.add_argument('--path_extr', type=str, required=True,
                       help='Path to calibration JSON file containing camera parameters')
    parser.add_argument('--basecam_pnp', type=str, default='cam1',help='Name of the base camera (default: cam1)')
    parser.add_argument('--path_output', type=str, default=None,
                       help='Output JSON file path (optional)')
    
    return parser

def load_point_correspondences(points_file):
    """Load 2D-3D point correspondences from JSON file."""
    with open(points_file, 'r') as f:
        correspondences = json.load(f)
    
    points_2d = []
    points_3d = []
    
    for corr in correspondences:
        points_2d.append(corr['2d'])
        points_3d.append(corr['3d'])
    
    return np.array(points_2d, dtype=np.float32), np.array(points_3d, dtype=np.float32)


def compute_world2base_transformation(points_2d, points_3d, K, dist):
    """Compute world to base transformation using cv2.solvePnP."""
    success, rvec, tvec = cv2.solvePnP(
        points_3d, points_2d, K, dist,
        flags=cv2.SOLVEPNP_ITERATIVE
    )
    
    if not success:
        raise RuntimeError("cv2.solvePnP failed to find a solution")
    
    # Convert rotation vector to rotation matrix
    R_world2base, _ = cv2.Rodrigues(rvec)
    T_world2base = tvec.flatten()
    
    return R_world2base, T_world2base


def rt_to_homogeneous_matrix(R, T):
    """Convert rotation matrix and translation vector to 4x4 homogeneous matrix."""
    matrix = np.eye(4)
    matrix[:3, :3] = R
    matrix[:3, 3] = T.flatten()
    return matrix

def homogeneous_matrix_to_rt(matrix):
    """Extract rotation matrix and translation vector from 4x4 homogeneous matrix."""
    R = matrix[:3, :3]
    T = matrix[:3, 3]
    return R, T

def compute_inverse_transformation(R, T):
    """Compute inverse transformation: if T_a2b = (R, t), then T_b2a = (R^T, -R^T @ t)."""
    R_inv = R.T
    T_inv = -R.T @ T.flatten()
    return R_inv, T_inv

def combine_transformations(R_a2b, T_a2b, R_b2c, T_b2c):
    # Convert to homogeneous matrices
    T_a2b_matrix = rt_to_homogeneous_matrix(R_a2b, T_a2b)
    T_b2c_matrix = rt_to_homogeneous_matrix(R_b2c, T_b2c)
    
    
    T_a2c_matrix = T_b2c_matrix@T_a2b_matrix
    
    # Extract R and T
    R_a2c, T_a2c = homogeneous_matrix_to_rt(T_a2c_matrix)
    
    return R_a2c, T_a2c

def format_transformation_matrix(R, T):
    """Format transformation as 4x4 homogeneous matrix."""
    return rt_to_homogeneous_matrix(R, T)


def save_results(output_file, results_dict):
    """Save transformation results to JSON file."""
    with open(output_file, 'w') as f:
        json.dump(results_dict, f, separators=(',', ':'), cls=NumpyEncoder)
    
    return results_dict

def main():
    """Main function."""
    parser = get_args_parser()
    args = parser.parse_args()

    log_dir = os.path.join(PATH_ASSETS_VIDEOS, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    logger = ColorLogger(log_dir, log_name='log.txt')

    recording = Recording(root_dir='.', path_cam_meta=args.path_extr, logger=logger)
    with open(args.path_extr, 'r') as f:
        output_json = json.load(f)
    calib_data = recording.cam_info

    K_base = calib_data[args.basecam_pnp]['cam_intrinsics']
    dist_base = np.zeros((5,))  # Assuming no distortion after undistortion step

    points_2d, points_3d = load_point_correspondences(args.path_points)
    R_world2basepnp, T_world2basepnp = compute_world2base_transformation(points_2d, points_3d, K_base, dist_base)
    print(args.basecam_pnp)
    print("R_world2basepnp:\n", R_world2basepnp)
    print("T_world2basepnp:\n", T_world2basepnp)

    print(calib_data[args.basecam_pnp])
    A_basejson2basepnp = calib_data[args.basecam_pnp]['cam_extrinsics'].copy()
    R_basejson2basepnp, T_basejson2basepnp = homogeneous_matrix_to_rt(A_basejson2basepnp)
    R_basepnp2basejson, T_basepnp2basejson = compute_inverse_transformation(R_basejson2basepnp, T_basejson2basepnp)

    R_check, T_check = combine_transformations(R_basejson2basepnp, T_basejson2basepnp, R_basepnp2basejson, T_basepnp2basejson)
    assert np.allclose(R_check, np.eye(3), atol=1e-6), "Inverse rotation check failed"
    assert np.allclose(T_check, np.zeros(3), atol=1e-6), "Inverse translation check failed"

    
    R_world2basejson, T_world2basejson = combine_transformations(R_world2basepnp, T_world2basepnp, R_basepnp2basejson, T_basepnp2basejson)

    output_json['camera_world2cam'] = {}
    for camera_name in calib_data.keys():
        
        # Get camera parameters and base2cam transformation
        A_basejson2cam = calib_data[camera_name]['cam_extrinsics'].copy()
        R_basejson2cam, T_basejson2cam = homogeneous_matrix_to_rt(A_basejson2cam)
        # Combine transformations
        R_world2cam, T_world2cam = combine_transformations(R_world2basejson, T_world2basejson, R_basejson2cam, T_basejson2cam)

        output_json['camera_world2cam'][camera_name] = {
            'R': R_world2cam.tolist(),
            'T': T_world2cam.tolist()
        }

        if camera_name == args.basecam_pnp:
            assert np.allclose(R_world2cam, R_world2basepnp, atol=1e-6), "Base camera rotation mismatch"
            assert np.allclose(T_world2cam, T_world2basepnp, atol=1e-6), "Base camera translation mismatch"
    
    # Save results if output file specified
    if args.path_output:
        save_results(args.path_output, output_json)
        print(f"\nAll results saved to: {args.path_output}")
    
    print("\nCalculation completed successfully for all cameras!")

if __name__ == "__main__":
    main()