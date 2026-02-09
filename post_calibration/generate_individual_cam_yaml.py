#!/usr/bin/env python3
"""
USAGE:
  python generate_individual_cam_yaml.py \
    --calib_json /path/to/calibration.json \
    --cam19_yaml /path/to/cam19.yaml \
    --output_dir /path/to/output/ \
    [--cameras cam19 cam1 cam2 ...]

Generate an independent YAML file for each camera containing:
- Intrinsics (K, dist)
- Mocap -> camX direct extrinsics (rvec, tvec)

This allows each camera to be used standalone without going through
the full transform chain at runtime.
"""

import argparse
import cv2
import numpy as np
import json
import os


def load_base_transforms(calib_file, refined_yaml):
    """Load base transforms from calibration.json and cam19 YAML."""
    # Load calibration.json
    with open(calib_file, 'r') as f:
        calib = json.load(f)

    # Load Mocap -> cam19 extrinsics
    fs = cv2.FileStorage(refined_yaml, cv2.FILE_STORAGE_READ)
    rvec_mocap_to_cam19 = fs.getNode('rvec').mat().flatten().astype(np.float64)
    tvec_mocap_to_cam19 = fs.getNode('tvec').mat().flatten().astype(np.float64)
    fs.release()

    R_mocap_to_cam19, _ = cv2.Rodrigues(rvec_mocap_to_cam19)

    # Compute cam19 -> cam1 (support both multical output formats)
    poses_key = 'camera_poses' if 'camera_poses' in calib else 'camera_base2cam'
    R_cam1_to_cam19 = np.array(calib[poses_key]['cam19_to_cam1']['R'])
    T_cam1_to_cam19 = np.array(calib[poses_key]['cam19_to_cam1']['T'])
    R_cam19_to_cam1 = R_cam1_to_cam19.T
    T_cam19_to_cam1 = -R_cam1_to_cam19.T @ T_cam1_to_cam19

    return calib, R_mocap_to_cam19, tvec_mocap_to_cam19, R_cam19_to_cam1, T_cam19_to_cam1


def compute_mocap_to_cam(cam_name, calib, R_mocap_to_cam19, tvec_mocap_to_cam19,
                          R_cam19_to_cam1, T_cam19_to_cam1):
    """
    Compute the direct Mocap -> camX transform.

    Transform chain: Mocap -> cam19 -> cam1 -> camX
    Merged into:     Mocap -> camX
    """
    if cam_name == 'cam19':
        # Direct Mocap -> cam19
        R_final = R_mocap_to_cam19
        T_final = tvec_mocap_to_cam19
    else:
        # Mocap -> cam19 -> cam1
        R_mocap_to_cam1 = R_cam19_to_cam1 @ R_mocap_to_cam19
        T_mocap_to_cam1 = R_cam19_to_cam1 @ tvec_mocap_to_cam19 + T_cam19_to_cam1

        if cam_name == 'cam1':
            R_final = R_mocap_to_cam1
            T_final = T_mocap_to_cam1
        else:
            # cam1 -> camX (from calibration.json)
            key = f"{cam_name}_to_cam1"
            poses_key = 'camera_poses' if 'camera_poses' in calib else 'camera_base2cam'
            R_cam1_to_camX = np.array(calib[poses_key][key]['R'])
            T_cam1_to_camX = np.array(calib[poses_key][key]['T'])

            # Mocap -> cam1 -> camX
            R_final = R_cam1_to_camX @ R_mocap_to_cam1
            T_final = R_cam1_to_camX @ T_mocap_to_cam1 + T_cam1_to_camX

    # Rotation matrix to rotation vector
    rvec_final, _ = cv2.Rodrigues(R_final)

    return rvec_final.flatten(), T_final.flatten()


def save_cam_yaml(cam_name, calib, rvec, tvec, output_dir):
    """Save camera parameters to a YAML file."""
    output_path = os.path.join(output_dir, f"{cam_name}.yaml")

    # Get intrinsics
    K = np.array(calib['cameras'][cam_name]['K']).reshape(3, 3)
    dist = np.array(calib['cameras'][cam_name]['dist'])

    # Save
    fs = cv2.FileStorage(output_path, cv2.FILE_STORAGE_WRITE)

    # Intrinsics
    fs.write('K', K)
    fs.write('dist', dist)

    # Extrinsics (Mocap -> camX)
    fs.write('rvec', rvec.reshape(3, 1))
    fs.write('tvec', tvec.reshape(3, 1))

    # Also save rotation matrix for convenience
    R, _ = cv2.Rodrigues(rvec)
    fs.write('R', R)

    fs.release()

    return output_path


def auto_detect_cameras(calib):
    """Auto-detect camera names from calibration.json. Returns cam19 first, then sorted rest."""
    cam_names = list(calib['cameras'].keys())
    # Separate cam19 from the rest
    others = sorted([c for c in cam_names if c != 'cam19'],
                    key=lambda x: int(x.replace('cam', '')) if x.replace('cam', '').isdigit() else x)
    cameras = []
    if 'cam19' in cam_names:
        cameras.append('cam19')
    cameras.extend(others)
    return cameras


def parse_args():
    parser = argparse.ArgumentParser(
        description='Generate individual camera YAML files with Mocap->camX direct transforms.')
    parser.add_argument('--calib_json', required=True,
                        help='Path to calibration.json from multical')
    parser.add_argument('--cam19_yaml', required=True,
                        help='Path to cam19.yaml (Mocap -> cam19 extrinsics)')
    parser.add_argument('--output_dir', required=True,
                        help='Output directory for individual cam YAML files')
    parser.add_argument('--cameras', nargs='+', default=None,
                        help='Camera names (default: auto-detect from calibration.json)')
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("Generate individual camera parameter files")
    print("=" * 60)

    os.makedirs(args.output_dir, exist_ok=True)

    # Load base transforms
    calib, R_mocap_to_cam19, tvec_mocap_to_cam19, R_cam19_to_cam1, T_cam19_to_cam1 = \
        load_base_transforms(args.calib_json, args.cam19_yaml)

    # Determine camera list
    if args.cameras is not None:
        cameras = args.cameras
    else:
        cameras = auto_detect_cameras(calib)
        print(f"\nAuto-detected cameras: {cameras}")

    print(f"\nOutput directory: {args.output_dir}\n")

    for cam_name in cameras:
        if cam_name not in calib['cameras']:
            print(f"[SKIP] {cam_name}: no intrinsic data")
            continue

        # Compute direct Mocap -> camX transform
        rvec, tvec = compute_mocap_to_cam(
            cam_name, calib,
            R_mocap_to_cam19, tvec_mocap_to_cam19,
            R_cam19_to_cam1, T_cam19_to_cam1
        )

        # Save
        output_path = save_cam_yaml(cam_name, calib, rvec, tvec, args.output_dir)

        print(f"[SAVED] {cam_name}.yaml")
        print(f"        rvec: [{rvec[0]:.6f}, {rvec[1]:.6f}, {rvec[2]:.6f}]")
        print(f"        tvec: [{tvec[0]:.6f}, {tvec[1]:.6f}, {tvec[2]:.6f}]")

    print(f"\n" + "=" * 60)
    print("Done!")
    print("=" * 60)

    # Print usage example
    print("\nUsage example:")
    print("""
```python
import cv2
import numpy as np

# Load single camera parameters
fs = cv2.FileStorage('cam1.yaml', cv2.FILE_STORAGE_READ)
K = fs.getNode('K').mat()
dist = fs.getNode('dist').mat()
rvec = fs.getNode('rvec').mat()
tvec = fs.getNode('tvec').mat()
fs.release()

# Directly project Mocap points to cam1
points_mocap = np.array([[x, y, z]])  # units: meters
pts_2d, _ = cv2.projectPoints(points_mocap, rvec, tvec, K, dist)
```
""")


if __name__ == '__main__':
    main()
