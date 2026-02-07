#!/usr/bin/env python3
"""
Compare camera extrinsics between two calibration JSON files.
Computes relative rotation and translation differences for each camera.
"""
import os
import sys
sys.path.append('..')
import json
import numpy as np
from scipy.spatial.transform import Rotation
import argparse

from utils.constants import PATH_ASSETS_VIDEOS

def load_calibration(json_path):
    """Load calibration JSON file."""
    with open(json_path, 'r') as f:
        return json.load(f)


def rotation_matrix_to_angle_axis(R):
    """Convert rotation matrix to axis-angle representation (in degrees)."""
    rot = Rotation.from_matrix(R)
    rotvec = rot.as_rotvec()
    angle = np.linalg.norm(rotvec) * 180 / np.pi
    if angle > 1e-6:
        axis = rotvec / np.linalg.norm(rotvec)
    else:
        axis = np.array([0, 0, 0])
    return angle, axis


def compute_relative_transformation(R1, T1, R2, T2):
    """
    Compute relative transformation from (R1, T1) to (R2, T2).

    The transformation from frame 1 to frame 2 is:
    R_rel = R2 @ R1^T
    T_rel = T2 - R2 @ R1^T @ T1

    Returns:
        - angle: rotation angle in degrees
        - axis: rotation axis
        - R_rel: relative rotation matrix
        - T_rel: relative translation vector
        - T_magnitude: magnitude of relative translation
    """
    R1 = np.array(R1)
    T1 = np.array(T1)
    R2 = np.array(R2)
    T2 = np.array(T2)

    # Relative rotation: R_rel = R2 @ R1^T
    R_rel = R2 @ R1.T

    # Relative translation: T_rel = T2 - R_rel @ T1
    T_rel = T2 - R_rel @ T1
    T_rel = T_rel*100  # Convert to cm
    T_magnitude = np.linalg.norm(T_rel)

    # Convert rotation to angle-axis
    angle, axis = rotation_matrix_to_angle_axis(R_rel)

    return angle, axis, R_rel, T_rel, T_magnitude


def compare_extrinsics(calib1, calib2):
    """Compare camera extrinsics between two calibrations."""

    camera_base2cam1 = calib1.get('camera_base2cam', {})
    camera_base2cam2 = calib2.get('camera_base2cam', {})

    # Find common cameras
    cameras1 = set(camera_base2cam1.keys())
    cameras2 = set(camera_base2cam2.keys())
    common_cameras = cameras1.intersection(cameras2)

    if not common_cameras:
        print("No common cameras found between the two calibration files.")
        return

    results = {}

    for cam_name in sorted(common_cameras):
        cam1 = camera_base2cam1[cam_name]
        cam2 = camera_base2cam2[cam_name]

        R1 = cam1['R']
        T1 = cam1['T']
        R2 = cam2['R']
        T2 = cam2['T']

        # Compute relative transformation
        angle, axis, R_rel, T_rel, T_magnitude = compute_relative_transformation(R1, T1, R2, T2)

        results[cam_name] = {
            'rotation_angle_deg': angle,
            'rotation_axis': axis,
            'rotation_matrix_rel': R_rel,
            'translation_rel': T_rel,
            'translation_magnitude': T_magnitude
        }

    """Print comparison results in a readable format."""
    print("\n" + "="*80)
    print("CAMERA EXTRINSICS COMPARISON")
    print("="*80)

    for cam_name, data in sorted(results.items()):
        print(f"\n{cam_name}:")
        print(f"    Rotation angle: {data['rotation_angle_deg']:.4f} degrees")
        print(f"    T_rel (cm): [{data['translation_rel'][0]:.2f}, {data['translation_rel'][1]:.2f}, {data['translation_rel'][2]:.2f}], Magnitude: {data['translation_magnitude']:.2f} cm")
    return results

def main():
    parser = argparse.ArgumentParser(
        description='Compare camera extrinsics between two calibration JSON files.'
    )
    parser.add_argument('--path_calib1', type=str, help='Path to first calibration JSON file')
    parser.add_argument('--path_calib2', type=str, help='Path to second calibration JSON file')

    args = parser.parse_args()

    # Load calibrations
    path_calib1 = os.path.join(PATH_ASSETS_VIDEOS, args.path_calib1)
    path_calib2 = os.path.join(PATH_ASSETS_VIDEOS, args.path_calib2)

    calib1 = load_calibration(path_calib1)
    calib2 = load_calibration(path_calib2)

    # Compare extrinsics
    results = compare_extrinsics(calib1, calib2)


if __name__ == '__main__':
    main()
