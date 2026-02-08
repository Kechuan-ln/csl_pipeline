#!/usr/bin/env python3
"""
cam19 GT Projection Visualization Tool

Renders skeleton + blade edges overlay on PrimeColor (cam19) video.
No sync needed - cam19 video and mocap data are from the same OptiTrack system (1:1 frame mapping).

Supports multiple blades (e.g., P7 with Rblade + lblade2).

Usage:
    # Visualize P7_1 session
    python post_calibration/verify_cam19_gt.py \
        --video /Volumes/KINGSTON/P7_output/P7_1/video.mp4 \
        --camera_yaml /Volumes/KINGSTON/P7_output/P7_1/cam19_refined.yaml \
        --gt_dir /Volumes/KINGSTON/P7_output/P7_1/ \
        --start 30 --duration 15 \
        --output /Volumes/KINGSTON/P7_output/P7_1/cam19_vis.mp4

    # Render full video at half scale
    python post_calibration/verify_cam19_gt.py \
        --video /Volumes/KINGSTON/P7_output/P7_1/video.mp4 \
        --camera_yaml /Volumes/KINGSTON/P7_output/P7_1/cam19_refined.yaml \
        --gt_dir /Volumes/KINGSTON/P7_output/P7_1/ \
        --scale 0.5 \
        --output cam19_full.mp4
"""

import argparse
import cv2
import numpy as np
from pathlib import Path
from tqdm import tqdm


# H36M 17-joint skeleton topology
H36M_BONES = [
    (0, 1), (1, 2), (2, 3),          # right leg
    (0, 4), (4, 5), (5, 6),          # left leg
    (0, 7), (7, 8), (8, 9), (9, 10), # spine
    (8, 11), (11, 12), (12, 13),     # left arm
    (8, 14), (14, 15), (15, 16),     # right arm
]

SKELETON_COLOR = (0, 255, 0)  # green

# Color palette for multiple blades
BLADE_COLORS = [
    {'edge': (0, 255, 255), 'fill': (255, 180, 0), 'name_color': (0, 200, 200)},   # yellow/orange
    {'edge': (255, 255, 0), 'fill': (0, 180, 255), 'name_color': (200, 200, 0)},   # cyan/blue
    {'edge': (255, 0, 255), 'fill': (180, 255, 0), 'name_color': (200, 0, 200)},   # magenta/green
]

BLADE_FILL_ALPHA = 0.35


def load_camera_yaml(yaml_path):
    """Load K, dist, rvec, tvec from OpenCV YAML file."""
    fs = cv2.FileStorage(str(yaml_path), cv2.FILE_STORAGE_READ)
    K = fs.getNode('camera_matrix').mat()
    if K is None:
        K = fs.getNode('K').mat()
    dist = fs.getNode('dist_coeffs').mat()
    if dist is None:
        dist = fs.getNode('dist').mat()
    rvec = fs.getNode('rvec').mat()
    tvec = fs.getNode('tvec').mat()
    fs.release()
    return K, dist, rvec, tvec


def project_points(points_3d, rvec, tvec, K, dist):
    """Project 3D points (mm) to 2D pixel coordinates."""
    valid_mask = ~np.any(np.isnan(points_3d), axis=1)
    pts_2d = np.full((len(points_3d), 2), np.nan, dtype=np.float32)

    if np.any(valid_mask):
        valid_pts = points_3d[valid_mask] / 1000.0  # mm to meters
        projected, _ = cv2.projectPoints(valid_pts, rvec, tvec, K, dist)
        pts_2d[valid_mask] = projected.reshape(-1, 2)

    return pts_2d


def draw_skeleton(frame, joints_2d, color=SKELETON_COLOR, thickness=2):
    """Draw H36M 17-joint skeleton."""
    valid = ~np.any(np.isnan(joints_2d), axis=1)

    # Draw bones
    for i, j in H36M_BONES:
        if valid[i] and valid[j]:
            pt1 = tuple(joints_2d[i].astype(int))
            pt2 = tuple(joints_2d[j].astype(int))
            cv2.line(frame, pt1, pt2, color, thickness)

    # Draw joints
    for idx in range(len(joints_2d)):
        if valid[idx]:
            pt = tuple(joints_2d[idx].astype(int))
            cv2.circle(frame, pt, 4, color, -1)


def draw_blade(frame, edges_2d, edge_color, fill_color, thickness=2, alpha=BLADE_FILL_ALPHA):
    """Draw blade edges with semi-transparent fill.

    Args:
        edges_2d: (E, 2, 2) - E edge pairs, 2 endpoints per edge, 2D coords
    """
    n_pairs = len(edges_2d)

    # Check valid edges
    valid = ~np.any(np.isnan(edges_2d), axis=(1, 2))

    if np.sum(valid) < 2:
        return

    left_2d = edges_2d[:, 0, :]   # (E, 2)
    right_2d = edges_2d[:, 1, :]  # (E, 2)

    # Semi-transparent fill between consecutive edges
    overlay = frame.copy()
    for i in range(n_pairs - 1):
        if valid[i] and valid[i + 1]:
            pts = np.array([
                left_2d[i], right_2d[i],
                right_2d[i + 1], left_2d[i + 1]
            ], dtype=np.int32)
            cv2.fillPoly(overlay, [pts], fill_color)

    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    # Draw cross-link edges
    for i in range(n_pairs):
        if valid[i]:
            pt1 = tuple(left_2d[i].astype(int))
            pt2 = tuple(right_2d[i].astype(int))
            cv2.line(frame, pt1, pt2, edge_color, thickness)

    # Draw left/right edge curves
    valid_left = left_2d[valid]
    valid_right = right_2d[valid]

    if len(valid_left) > 1:
        pts_left = valid_left.astype(np.int32).reshape(-1, 1, 2)
        pts_right = valid_right.astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(frame, [pts_left], False, edge_color, thickness)
        cv2.polylines(frame, [pts_right], False, edge_color, thickness)


def load_blade_files(gt_dir):
    """Auto-detect and load all blade edge files in gt_dir.

    Returns:
        List of dicts with keys: 'name', 'data', 'edge_color', 'fill_color', 'name_color'
    """
    # Filter out macOS resource fork files (._*)
    blade_files = sorted([f for f in gt_dir.glob('*_edges.npy') if not f.name.startswith('._')])

    # Fallback to aligned_edges.npy if no blade-specific files found
    if not blade_files:
        aligned_path = gt_dir / 'aligned_edges.npy'
        if aligned_path.exists():
            blade_files = [aligned_path]

    if not blade_files:
        return []

    blades = []
    for i, blade_path in enumerate(blade_files):
        color_idx = i % len(BLADE_COLORS)
        colors = BLADE_COLORS[color_idx]

        blades.append({
            'name': blade_path.stem.replace('_edges', ''),
            'data': np.load(blade_path, allow_pickle=True),
            'edge_color': colors['edge'],
            'fill_color': colors['fill'],
            'name_color': colors['name_color'],
        })

    return blades


def draw_hud(frame, frame_idx, n_joints, blade_info_list):
    """Draw frame info overlay.

    Args:
        blade_info_list: List of (blade_name, color) tuples
    """
    lines = [
        (f"Frame: {frame_idx}  Joints: {n_joints}", (255, 255, 255)),
    ]

    # Add blade info
    if blade_info_list:
        blade_text = "Blades: " + ", ".join([name for name, _ in blade_info_list])
        lines.append((blade_text, (255, 255, 255)))

    for i, (text, color) in enumerate(lines):
        y = 28 + i * 26
        # Black outline
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3)
        # Colored text
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 1)


def main():
    parser = argparse.ArgumentParser(description='cam19 GT projection visualization')
    parser.add_argument('--video', required=True, help='PrimeColor video file')
    parser.add_argument('--camera_yaml', required=True, help='cam19 YAML file (refined or initial)')
    parser.add_argument('--gt_dir', required=True, help='GT directory (containing skeleton_h36m.npy, *_edges.npy)')
    parser.add_argument('--output', default='cam19_vis.mp4', help='Output video path')
    parser.add_argument('--start', type=float, default=0, help='Start time in seconds (default: 0)')
    parser.add_argument('--duration', type=float, default=-1, help='Duration in seconds (-1 for full video)')
    parser.add_argument('--scale', type=float, default=1.0, help='Output scale (default: 1.0)')
    parser.add_argument('--fps', type=float, default=None, help='Output FPS (default: match input video fps)')

    args = parser.parse_args()

    gt_dir = Path(args.gt_dir)

    # Load camera parameters
    print(f"Loading camera: {args.camera_yaml}")
    K, dist, rvec, tvec = load_camera_yaml(args.camera_yaml)

    # Load skeleton GT
    skeleton_path = gt_dir / 'skeleton_h36m.npy'
    if not skeleton_path.exists():
        raise FileNotFoundError(f"Skeleton not found: {skeleton_path}")

    skeleton = np.load(skeleton_path)
    print(f"Skeleton: {skeleton_path.name} {skeleton.shape}")

    # Load blade edges (multi-blade support)
    blades = load_blade_files(gt_dir)
    if blades:
        print(f"Blades: {len(blades)} found")
        for blade in blades:
            print(f"  {blade['name']}: {blade['data'].shape}")
    else:
        print("No blade edges found")

    # Open video
    print(f"Opening video: {args.video}")
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Video: {width}x{height} @ {video_fps:.2f}fps, {total_frames} frames")

    # Determine frame range
    start_frame = int(args.start * video_fps)
    if args.duration > 0:
        end_frame = min(start_frame + int(args.duration * video_fps), total_frames, len(skeleton))
    else:
        end_frame = min(total_frames, len(skeleton))

    print(f"Rendering frames: [{start_frame}, {end_frame}) ({end_frame - start_frame} frames)")

    # Output setup
    out_width = int(width * args.scale)
    out_height = int(height * args.scale)

    # Default to input video fps if not specified
    output_fps = args.fps if args.fps is not None else video_fps

    # Use h264_videotoolbox for macOS hardware encoding
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    out = cv2.VideoWriter(args.output, fourcc, output_fps, (out_width, out_height))

    if not out.isOpened():
        raise RuntimeError(f"Cannot create output video: {args.output}")

    print(f"Output: {args.output} ({out_width}x{out_height} @ {output_fps}fps)")

    # Scale camera matrix
    K_scaled = K.copy()
    K_scaled[0, 0] *= args.scale
    K_scaled[1, 1] *= args.scale
    K_scaled[0, 2] *= args.scale
    K_scaled[1, 2] *= args.scale

    # Process frames
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    for frame_idx in tqdm(range(start_frame, end_frame), desc="Rendering"):
        ret, frame = cap.read()
        if not ret:
            break

        # Resize frame
        if args.scale != 1.0:
            frame = cv2.resize(frame, (out_width, out_height), interpolation=cv2.INTER_AREA)

        # Draw skeleton
        n_valid_joints = 0
        if frame_idx < len(skeleton):
            skel_3d = skeleton[frame_idx]  # (17, 3) in mm
            skel_2d = project_points(skel_3d, rvec, tvec, K_scaled, dist)
            draw_skeleton(frame, skel_2d)
            n_valid_joints = np.sum(~np.isnan(skel_3d).any(axis=1))

        # Draw blades
        blade_info_list = []
        for blade in blades:
            if frame_idx < len(blade['data']):
                edges_3d = blade['data'][frame_idx]  # (E, 2, 3) in mm
                E = edges_3d.shape[0]
                edges_flat = edges_3d.reshape(-1, 3)  # (E*2, 3)
                edges_2d_flat = project_points(edges_flat, rvec, tvec, K_scaled, dist)
                edges_2d = edges_2d_flat.reshape(E, 2, 2)  # (E, 2, 2)

                draw_blade(frame, edges_2d, blade['edge_color'], blade['fill_color'])
                blade_info_list.append((blade['name'], blade['name_color']))

        # Draw HUD
        draw_hud(frame, frame_idx, n_valid_joints, blade_info_list)

        out.write(frame)

    cap.release()
    out.release()
    print(f"\nDone! Output saved to: {args.output}")


if __name__ == '__main__':
    main()
