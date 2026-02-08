#!/usr/bin/env python3
"""
Extract PrimeColor (cam19) extrinsics from OptiTrack .mcal calibration file.

Converts OptiTrack coordinate system (Y-up) to OpenCV (Y-down) and saves
as OpenCV FileStorage YAML suitable for the calibration pipeline.

The .mcal file is shared across all sessions in a recording batch (e.g., P7_1-P7_5).
Each session later refines cam19 via refine_extrinsics.py.

Usage:
    # Auto-detect PrimeColor by resolution (1920x1080)
    python mcal_to_cam19_yaml.py /path/to/Cal.mcal -o /path/to/cam19_initial.yaml

    # Specify camera ID explicitly
    python mcal_to_cam19_yaml.py /path/to/Cal.mcal -o /path/to/cam19_initial.yaml --camera_id 13

    # Dry run: print extracted parameters without saving
    python mcal_to_cam19_yaml.py /path/to/Cal.mcal --dry_run
"""

import argparse
import codecs
import sys
import xml.etree.ElementTree as ET

import cv2
import numpy as np


def load_mcal(mcal_path):
    """Load and parse .mcal file (UTF-16-LE with BOM)."""
    with codecs.open(mcal_path, "r", "utf-16-le") as f:
        content = f.read()
    if content.startswith("\ufeff"):
        content = content[1:]
    return ET.fromstring(content)


def find_primecolor_camera(root, camera_id=None):
    """
    Find the PrimeColor camera element in the mcal XML.

    If camera_id is given, match by CameraID.
    Otherwise, auto-detect by resolution (1920x1080, the PrimeColor spec).
    Returns (camera_element, camera_id_str).
    """
    cameras = root.findall(".//Camera")
    if not cameras:
        raise ValueError("No cameras found in mcal file")

    if camera_id is not None:
        for cam in cameras:
            props = cam.find("Properties")
            if props is not None and props.get("CameraID") == str(camera_id):
                return cam, str(camera_id)
        raise ValueError(f"CameraID={camera_id} not found in mcal. "
                         f"Available IDs: {[c.find('Properties').get('CameraID') for c in cameras]}")

    # Auto-detect: PrimeColor is 1920x1080, OptiTrack IR cameras are 1664x1088
    for cam in cameras:
        attrs = cam.find("Attributes")
        if attrs is None:
            continue
        w = int(attrs.get("ImagerPixelWidth", 0))
        h = int(attrs.get("ImagerPixelHeight", 0))
        if w == 1920 and h == 1080:
            cid = cam.find("Properties").get("CameraID")
            return cam, cid

    raise ValueError("Could not auto-detect PrimeColor camera (no 1920x1080 camera found). "
                     "Specify --camera_id explicitly.")


def extract_cam19_params(cam_element):
    """
    Extract intrinsics and extrinsics from a camera element.

    Uses IntrinsicStandardCameraModel (OpenCV-compatible distortion),
    NOT Intrinsic (OptiTrack internal model).
    Applies Y-axis flip: OptiTrack (Y-up) → OpenCV (Y-down).

    Returns: K (3x3), dist (1x5), rvec (3x1), tvec (3x1), R (3x3)
    """
    # Intrinsics from StandardCameraModel
    i = cam_element.find("IntrinsicStandardCameraModel")
    if i is None:
        raise ValueError("IntrinsicStandardCameraModel not found. "
                         "Check that the mcal was exported with standard model.")

    K = np.array([
        [float(i.get("HorizontalFocalLength")), 0, float(i.get("LensCenterX"))],
        [0, float(i.get("VerticalFocalLength")), float(i.get("LensCenterY"))],
        [0, 0, 1],
    ], dtype=np.float64)

    dist = np.array([[
        float(i.get("k1")),
        float(i.get("k2")),
        float(i.get("TangentialX")),
        float(i.get("TangentialY")),
        float(i.get("k3")),
    ]], dtype=np.float64)

    # Extrinsics
    e = cam_element.find("Extrinsic")
    if e is None:
        raise ValueError("Extrinsic element not found for this camera")

    R_optitrack = np.array([
        [float(e.get(f"OrientMatrix{j}")) for j in range(k * 3, k * 3 + 3)]
        for k in range(3)
    ], dtype=np.float64)
    position = np.array([
        float(e.get("X")),
        float(e.get("Y")),
        float(e.get("Z")),
    ], dtype=np.float64)

    # OptiTrack Y-up → OpenCV Y-down
    Fyz = np.diag([1.0, -1.0, -1.0])
    R = Fyz @ R_optitrack.T
    rvec, _ = cv2.Rodrigues(R)
    tvec = (-R @ position).reshape(3, 1)

    return K, dist, rvec, tvec, R


def save_cam19_yaml(output_path, K, dist, rvec, tvec, R):
    """Save camera parameters as OpenCV FileStorage YAML."""
    fs = cv2.FileStorage(output_path, cv2.FILE_STORAGE_WRITE)
    fs.write("camera_matrix", K)
    fs.write("K", K)
    fs.write("dist_coeffs", dist)
    fs.write("dist", dist)
    fs.write("rvec", rvec)
    fs.write("tvec", tvec)
    fs.write("R", R)
    fs.release()


def main():
    parser = argparse.ArgumentParser(
        description="Extract PrimeColor (cam19) params from OptiTrack .mcal file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mcal_to_cam19_yaml.py Cal.mcal -o cam19_initial.yaml
  python mcal_to_cam19_yaml.py Cal.mcal -o cam19_initial.yaml --camera_id 13
  python mcal_to_cam19_yaml.py Cal.mcal --dry_run
        """,
    )
    parser.add_argument("mcal_path", help="Path to .mcal file (UTF-16-LE)")
    parser.add_argument("-o", "--output", help="Output YAML path (cam19_initial.yaml)")
    parser.add_argument("--camera_id", type=int, default=None,
                        help="OptiTrack CameraID for PrimeColor (default: auto-detect by 1920x1080)")
    parser.add_argument("--dry_run", action="store_true",
                        help="Print parameters without saving")

    args = parser.parse_args()

    if not args.output and not args.dry_run:
        parser.error("Either -o/--output or --dry_run is required")

    # Parse mcal
    print(f"Loading: {args.mcal_path}")
    root = load_mcal(args.mcal_path)

    # Find PrimeColor
    cam, cid = find_primecolor_camera(root, args.camera_id)
    serial = cam.get("Serial", "unknown")
    attrs = cam.find("Attributes")
    w = attrs.get("ImagerPixelWidth") if attrs is not None else "?"
    h = attrs.get("ImagerPixelHeight") if attrs is not None else "?"
    print(f"PrimeColor found: CameraID={cid}, Serial={serial}, {w}x{h}")

    # Extract parameters
    K, dist, rvec, tvec, R = extract_cam19_params(cam)

    print(f"\nIntrinsics (K):")
    print(f"  fx={K[0,0]:.3f}  fy={K[1,1]:.3f}  cx={K[0,2]:.3f}  cy={K[1,2]:.3f}")
    print(f"Distortion: {dist.flatten()}")
    print(f"Position (tvec): {tvec.flatten()}")
    print(f"Rotation (rvec): {rvec.flatten()}")

    if args.dry_run:
        print("\n[Dry run] No file saved.")
        return 0

    save_cam19_yaml(args.output, K, dist, rvec, tvec, R)
    print(f"\nSaved: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
