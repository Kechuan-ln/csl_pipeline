#!/usr/bin/env python3
"""
Interactive Extrinsic Refinement Tool

Refine camera extrinsics by clicking on markers and their correct 2D positions.

Usage:
    # Direct mode (PrimeColor / cam19)
    python refine_extrinsics.py \\
        --markers cam19/markers.npy \\
        --video cam19/PrimeColor.avi \\
        --camera cam19.yaml --output refined_cam19.yaml

    # Sync mode (GoPro cameras)
    python refine_extrinsics.py \\
        --markers action2_data/bone_markers.npy \\
        --video cam1/GX010409.MP4 \\
        --camera individual_cam_params/cam1.yaml \\
        --output refined_cam1.yaml \\
        --sync action2_data/sync_mapping.json \\
        --camera-offset 0

Controls:
    a/d     : Prev/Next frame
    s/S     : -100 frames / -100 frames
    w/W     : -2000 / +2000 frames (fast jump)
    f       : Find stable frame (search forward)
    D       : +100 frames
    [ ]     : Time offset -1/+1 frame
    , .     : Time offset -0.5/+0.5 frame
    L-click : Select nearest marker
    R-click : Place correction for selected marker
    o       : Optimize extrinsics only (solvePnP)
    O       : Optimize full (scipy least_squares, 14 params)
    z       : Undo last calibration pair
    t       : Toggle Y/Z coordinate flip
    e       : Export refined parameters + sync JSON
    r       : Reset all
    c       : Cancel current selection
    q       : Quit
"""

import argparse
import json
import cv2
import numpy as np
from pathlib import Path
from scipy.optimize import least_squares


def load_camera_yaml(yaml_path):
    """Load camera parameters from OpenCV YAML."""
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


def save_camera_yaml(yaml_path, K, dist, rvec, tvec):
    """Save camera parameters to OpenCV YAML."""
    fs = cv2.FileStorage(str(yaml_path), cv2.FILE_STORAGE_WRITE)
    fs.write('camera_matrix', K)
    fs.write('K', K)
    fs.write('dist_coeffs', dist)
    fs.write('dist', dist)
    fs.write('rvec', rvec)
    fs.write('tvec', tvec)
    fs.release()


class ExtrinsicRefiner:
    def __init__(self, video_path, markers, marker_names, K, dist, rvec, tvec,
                 start_frame=0, sync_config=None, camera_offset=0.0, mocap_start_frame=0):
        self.cap = cv2.VideoCapture(str(video_path))
        self.markers = markers  # (N, M, 3) in mm
        self.marker_names = marker_names

        # Camera parameters
        self.K = K.copy()
        self.dist = dist.copy()
        self.rvec = rvec.copy()
        self.tvec = tvec.copy()

        # Initial values for reset
        self.K_init = K.copy()
        self.dist_init = dist.copy()
        self.rvec_init = rvec.copy()
        self.tvec_init = tvec.copy()

        # Sync mode
        self.sync_mode = sync_config is not None
        self.camera_offset = camera_offset
        self.mocap_start_frame = mocap_start_frame
        if self.sync_mode:
            self.gopro_fps = sync_config['gopro_fps']
            self.mocap_fps = sync_config['primecolor_fps']
            self.offset_seconds = sync_config['offset_seconds']
        else:
            self.gopro_fps = None
            self.mocap_fps = None
            self.offset_seconds = None

        # Coordinate flip toggle
        self.flip_y = False

        # Frame state
        self.frame_idx = start_frame
        video_frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if self.sync_mode:
            self.n_frames = video_frame_count
        else:
            self.n_frames = min(len(markers), video_frame_count)
        self.current_frame = None

        # Time offset (in marker frames, can be fractional)
        self.time_offset = 0.0

        # Video info
        self.video_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.video_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.scale = min(1.0, 1920 / self.video_width)  # Scale for display

        # Calibration points
        self.calib_points_3d = []
        self.calib_points_2d = []

        # Current frame data
        self.frame_points_3d = []
        self.frame_points_2d = []
        self.frame_names = []

        # Selection state
        self.selected_idx = -1

        # Per-marker velocities (index -> mm/frame)
        self.marker_velocities = {}

        # Window
        self.window_name = "Extrinsic Refinement"
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.window_name, self.on_mouse)

        mode_str = "SYNC" if self.sync_mode else "DIRECT"
        print(f"Mode: {mode_str}")
        print(f"Video: {self.video_width}x{self.video_height}, {self.n_frames} frames")
        print(f"Markers: {markers.shape}")
        if self.sync_mode:
            print(f"Sync: offset={self.offset_seconds:.6f}s, gopro_fps={self.gopro_fps:.2f}, mocap_fps={self.mocap_fps:.1f}")
            print(f"Camera offset: {self.camera_offset} gopro frames, mocap_start_frame: {self.mocap_start_frame}")
        print(f"Display scale: {self.scale:.2f}")

    def get_current_mocap_frame(self):
        """Get the computed mocap frame index for the current video frame."""
        if self.sync_mode:
            t_gopro = self.frame_idx / self.gopro_fps
            t_mocap = t_gopro - self.offset_seconds
            f_mocap = t_mocap * self.mocap_fps - self.mocap_start_frame
            f_mocap += self.camera_offset * (self.mocap_fps / self.gopro_fps)
            f_mocap += self.time_offset
            return f_mocap
        else:
            return self.frame_idx + self.time_offset

    def _interpolate_markers(self, marker_idx):
        """Interpolate markers at a (possibly fractional) index. Returns None if out of bounds."""
        if marker_idx < 0 or marker_idx >= len(self.markers) - 1:
            return None

        if marker_idx == int(marker_idx):
            idx = int(marker_idx)
            if idx >= len(self.markers):
                return None
            return self.markers[idx]

        idx0 = int(marker_idx)
        idx1 = idx0 + 1
        alpha = marker_idx - idx0

        if idx1 >= len(self.markers):
            return self.markers[idx0]

        m0 = self.markers[idx0]
        m1 = self.markers[idx1]

        result = np.full_like(m0, np.nan)
        valid = ~np.isnan(m0).any(axis=1) & ~np.isnan(m1).any(axis=1)
        result[valid] = (1 - alpha) * m0[valid] + alpha * m1[valid]

        return result

    def get_markers_with_offset(self, frame_idx):
        """Get marker data with time offset applied, with interpolation for fractional offsets.

        Direct mode: marker_idx = frame_idx + time_offset
        Sync mode: time-based conversion from GoPro frame to mocap frame
        """
        if self.sync_mode:
            t_gopro = frame_idx / self.gopro_fps
            t_mocap = t_gopro - self.offset_seconds
            f_mocap = t_mocap * self.mocap_fps - self.mocap_start_frame
            f_mocap += self.camera_offset * (self.mocap_fps / self.gopro_fps)
            f_mocap += self.time_offset  # manual fine-tune
            return self._interpolate_markers(f_mocap)
        else:
            marker_idx = frame_idx + self.time_offset
            return self._interpolate_markers(marker_idx)

    def on_mouse(self, event, x, y, flags, param):
        # Convert display coords to original video coords
        x_orig = x / self.scale
        y_orig = y / self.scale

        if event == cv2.EVENT_LBUTTONDOWN:
            # Left click: select nearest marker
            threshold = 100
            best_idx = -1
            min_dist = threshold

            for i, pt in enumerate(self.frame_points_2d):
                dist = np.sqrt((x_orig - pt[0])**2 + (y_orig - pt[1])**2)
                if dist < min_dist:
                    min_dist = dist
                    best_idx = i

            if best_idx >= 0:
                self.selected_idx = best_idx
                name = self.frame_names[best_idx]
                print(f"Selected: {name}. Right-click to place correction.")
            else:
                self.selected_idx = -1
            self.update_display()

        elif event == cv2.EVENT_RBUTTONDOWN:
            # Right click: place correction for selected marker
            if self.selected_idx >= 0:
                p3d = self.frame_points_3d[self.selected_idx].copy()
                if self.flip_y:
                    p3d = np.array([p3d[0], -p3d[1], -p3d[2]], dtype=p3d.dtype)
                self.calib_points_3d.append(p3d)
                self.calib_points_2d.append((x_orig, y_orig))

                name = self.frame_names[self.selected_idx]
                print(f"Added: {name} -> ({x_orig:.0f}, {y_orig:.0f}). Total pairs: {len(self.calib_points_3d)}")

                self.selected_idx = -1
                self.update_display()

    def get_frame_data(self):
        """Load video frame and corresponding 3D markers."""
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.frame_idx)
        ret, frame = self.cap.read()
        if not ret:
            return None

        self.current_frame = frame

        # Get valid markers for this frame (with time offset)
        self.frame_points_3d = []
        self.frame_names = []

        markers_frame = self.get_markers_with_offset(self.frame_idx)
        if markers_frame is not None:
            for i, (pos, name) in enumerate(zip(markers_frame, self.marker_names)):
                if not np.isnan(pos).any():
                    self.frame_points_3d.append(pos / 1000.0)  # mm to m
                    self.frame_names.append(name)

        self.frame_points_3d = np.array(self.frame_points_3d, dtype=np.float32) if self.frame_points_3d else np.zeros((0, 3), dtype=np.float32)

        # Compute per-marker velocities for color mapping
        self.compute_marker_velocities()

        # Project to 2D (apply flip if enabled)
        if len(self.frame_points_3d) > 0:
            pts_for_proj = self.frame_points_3d.copy()
            if self.flip_y:
                pts_for_proj[:, 1] = -pts_for_proj[:, 1]
                pts_for_proj[:, 2] = -pts_for_proj[:, 2]
            pts_2d, _ = cv2.projectPoints(pts_for_proj, self.rvec, self.tvec, self.K, self.dist)
            self.frame_points_2d = pts_2d.reshape(-1, 2)
        else:
            self.frame_points_2d = np.zeros((0, 2))

        return frame

    def compute_marker_velocities(self, window=5):
        """Compute per-marker velocity (mm/frame) over a window around the current frame.

        Returns a dict mapping frame_names index -> velocity in mm/frame.
        Velocity 0 = stationary, higher = faster.
        """
        self.marker_velocities = {}

        # Get marker positions for adjacent frames using the offset-aware method
        half_w = window // 2
        frame_markers = []
        for delta in range(-half_w, half_w + 1):
            test_frame = self.frame_idx + delta
            if test_frame < 0 or test_frame >= self.n_frames:
                frame_markers.append(None)
            else:
                frame_markers.append(self.get_markers_with_offset(test_frame))

        if frame_markers[half_w] is None:
            return

        current_markers = frame_markers[half_w]
        n_markers = current_markers.shape[0]

        # Build mapping: original marker index -> frame_names index
        valid_orig_indices = []
        for i, pos in enumerate(current_markers):
            if not np.isnan(pos).any():
                valid_orig_indices.append(i)

        # Compute velocity for each original marker
        for orig_idx in range(n_markers):
            if np.isnan(current_markers[orig_idx]).any():
                continue

            # Gather displacements from consecutive pairs
            speeds = []
            for t in range(len(frame_markers) - 1):
                m0 = frame_markers[t]
                m1 = frame_markers[t + 1]
                if m0 is None or m1 is None:
                    continue
                if np.isnan(m0[orig_idx]).any() or np.isnan(m1[orig_idx]).any():
                    continue
                speeds.append(np.linalg.norm(m1[orig_idx] - m0[orig_idx]))

            if speeds:
                avg_speed = np.mean(speeds)  # mm/frame
            else:
                avg_speed = 0.0

            # Map to frame_names index
            if orig_idx in valid_orig_indices:
                frame_idx = valid_orig_indices.index(orig_idx)
                self.marker_velocities[frame_idx] = avg_speed

    def get_velocity_color(self, velocity_mm):
        """Map velocity to BGR color. Slow (near 0) = vivid red, fast = faded/light pink.

        velocity_mm: speed in mm/frame
        Returns: (B, G, R) tuple
        """
        # Thresholds: 0 mm/frame = pure vivid red, >= 10 mm/frame = very faded
        max_speed = 10.0  # mm/frame, above this is fully faded
        t = min(velocity_mm / max_speed, 1.0)  # 0=still, 1=fast

        # Vivid red: (0, 0, 255) -> Faded pink: (200, 180, 230)
        b = int(0 + t * 200)
        g = int(0 + t * 180)
        r = int(255 - t * 25)  # stays mostly red but slightly desaturated
        return (b, g, r)

    def find_stable_frame(self, min_stable_frames=15, motion_threshold_mm=1.0, search_limit=2000):
        """Search forward for a stable region where markers barely move."""
        print(f"Searching for stable frames (min {min_stable_frames} frames, threshold {motion_threshold_mm:.2f}mm)...")

        stable_start = None
        stable_count = 0
        prev_markers = None

        for i in range(search_limit):
            # Use get_markers_with_offset so it works in both modes
            test_frame = self.frame_idx + i + 1
            if not self.sync_mode and test_frame >= self.n_frames:
                break

            markers = self.get_markers_with_offset(test_frame)
            if markers is None:
                stable_start = None
                stable_count = 0
                prev_markers = None
                continue

            # Get valid marker positions
            valid_mask = ~np.isnan(markers).any(axis=1)
            if valid_mask.sum() < 2:
                stable_start = None
                stable_count = 0
                prev_markers = None
                continue

            if prev_markers is None:
                prev_markers = markers.copy()
                stable_start = test_frame
                stable_count = 1
                continue

            # Average motion for markers valid in both frames
            both_valid = valid_mask & ~np.isnan(prev_markers).any(axis=1)
            if both_valid.sum() < 2:
                prev_markers = markers.copy()
                stable_start = test_frame
                stable_count = 1
                continue

            motions = np.linalg.norm(markers[both_valid] - prev_markers[both_valid], axis=1)
            avg_motion = motions.mean()

            if avg_motion < motion_threshold_mm:
                stable_count += 1
                if stable_count >= min_stable_frames:
                    target = stable_start + stable_count // 2
                    print(f"Found stable region: frames {stable_start}-{test_frame} ({stable_count} frames)")
                    print(f"Jumping to middle frame: {target}")
                    self.frame_idx = min(target, self.n_frames - 1)
                    self.selected_idx = -1
                    self.get_frame_data()
                    self.update_display()
                    return
            else:
                stable_start = test_frame
                stable_count = 1

            prev_markers = markers.copy()

        print(f"No stable region found in next {search_limit} frames.")

    def optimize_extrinsics(self):
        """Optimize extrinsics only using solvePnP."""
        n_points = len(self.calib_points_3d)
        if n_points < 4:
            print(f"Need at least 4 points (have {n_points})")
            return

        obj_pts = np.array(self.calib_points_3d, dtype=np.float32)
        img_pts = np.array(self.calib_points_2d, dtype=np.float32)

        # Error before
        proj_before, _ = cv2.projectPoints(obj_pts, self.rvec, self.tvec, self.K, self.dist)
        proj_before = proj_before.squeeze()

        # Debug: show actual coordinates
        print(f"\n[DEBUG] Calibration points ({n_points} pts):")
        for i in range(len(obj_pts)):
            diff = img_pts[i] - proj_before[i]
            dist = np.linalg.norm(diff)
            print(f"  Point {i}: target={img_pts[i]}, projected={proj_before[i]}, diff={diff}, dist={dist:.1f}px")

        err_before = np.mean(np.linalg.norm(img_pts - proj_before, axis=1))

        print(f"\n[Extrinsics Only] Optimizing with {n_points} points...")
        print(f"Error before: {err_before:.2f} px")

        ret, rvec_new, tvec_new = cv2.solvePnP(
            obj_pts, img_pts, self.K, self.dist,
            rvec=self.rvec.copy(), tvec=self.tvec.copy(),
            useExtrinsicGuess=True,
            flags=cv2.SOLVEPNP_ITERATIVE
        )

        if ret:
            self.rvec = rvec_new
            self.tvec = tvec_new

            proj_after, _ = cv2.projectPoints(obj_pts, self.rvec, self.tvec, self.K, self.dist)
            err_after = np.mean(np.linalg.norm(img_pts - proj_after.squeeze(), axis=1))

            print(f"Success! Error: {err_before:.2f} -> {err_after:.2f} px")
            print(f"rvec: {self.rvec.flatten()}")
            print(f"tvec: {self.tvec.flatten()}")
            self.update_display()
        else:
            print("solvePnP failed!")

    def optimize_full(self):
        """Optimize intrinsics + extrinsics jointly using scipy.least_squares (14 params)."""
        n_points = len(self.calib_points_3d)
        if n_points < 6:
            print(f"Need at least 6 points for full calibration (have {n_points})")
            return

        obj_pts = np.array(self.calib_points_3d, dtype=np.float64)
        img_pts = np.array(self.calib_points_2d, dtype=np.float64)

        # Error before
        proj_before, _ = cv2.projectPoints(obj_pts, self.rvec, self.tvec, self.K, self.dist)
        err_before = np.mean(np.linalg.norm(img_pts - proj_before.squeeze(), axis=1))

        print(f"\n[Full Calibration - scipy] Optimizing with {n_points} points...")
        print(f"Error before: {err_before:.2f} px")
        print(f"K before:\n{self.K}")

        # Initial parameters: [fx, fy, cx, cy, k1, k2, p1, p2, rx, ry, rz, tx, ty, tz]
        fx, fy = self.K[0, 0], self.K[1, 1]
        cx, cy = self.K[0, 2], self.K[1, 2]
        d = self.dist.flatten()
        k1 = d[0] if len(d) > 0 else 0
        k2 = d[1] if len(d) > 1 else 0
        p1 = d[2] if len(d) > 2 else 0
        p2 = d[3] if len(d) > 3 else 0

        x0 = np.array([
            fx, fy, cx, cy,
            k1, k2, p1, p2,
            self.rvec.flatten()[0], self.rvec.flatten()[1], self.rvec.flatten()[2],
            self.tvec.flatten()[0], self.tvec.flatten()[1], self.tvec.flatten()[2]
        ], dtype=np.float64)

        def residuals(params):
            fx_, fy_, cx_, cy_, k1_, k2_, p1_, p2_, rx, ry, rz, tx, ty, tz = params
            K_ = np.array([[fx_, 0, cx_], [0, fy_, cy_], [0, 0, 1]], dtype=np.float64)
            dist_ = np.array([k1_, k2_, p1_, p2_, 0], dtype=np.float64)
            rvec_ = np.array([rx, ry, rz], dtype=np.float64)
            tvec_ = np.array([tx, ty, tz], dtype=np.float64)
            proj, _ = cv2.projectPoints(obj_pts, rvec_, tvec_, K_, dist_)
            return (proj.reshape(-1, 2) - img_pts).flatten()

        try:
            result = least_squares(
                residuals, x0,
                method='lm',
                ftol=1e-12, xtol=1e-12, gtol=1e-12,
                max_nfev=5000,
                verbose=1
            )

            err_initial = np.sum(residuals(x0)**2)
            if result.success or result.cost < err_initial:
                params = result.x
                fx_new, fy_new, cx_new, cy_new = params[0:4]
                k1_new, k2_new, p1_new, p2_new = params[4:8]

                self.K = np.array([
                    [fx_new, 0, cx_new],
                    [0, fy_new, cy_new],
                    [0, 0, 1]
                ], dtype=np.float64)
                self.dist = np.array([[k1_new, k2_new, p1_new, p2_new, 0]], dtype=np.float64)
                self.rvec = params[8:11].reshape(3, 1).astype(np.float64)
                self.tvec = params[11:14].reshape(3, 1).astype(np.float64)

                proj_after, _ = cv2.projectPoints(obj_pts, self.rvec, self.tvec, self.K, self.dist)
                proj_after = proj_after.squeeze()
                err_after = np.mean(np.linalg.norm(img_pts - proj_after, axis=1))

                print(f"\nSuccess! Error: {err_before:.2f} -> {err_after:.2f} px")
                print(f"K after:\n{self.K}")
                print(f"dist: {self.dist.flatten()}")

                # Per-point errors
                for i in range(len(obj_pts)):
                    e = np.linalg.norm(img_pts[i] - proj_after[i])
                    print(f"  Point {i}: {e:.2f} px")

                # Intrinsic changes
                print(f"Intrinsic changes: fx {fx:.1f}->{fx_new:.1f}, fy {fy:.1f}->{fy_new:.1f}, "
                      f"cx {cx:.1f}->{cx_new:.1f}, cy {cy:.1f}->{cy_new:.1f}")

                self.update_display()
            else:
                print(f"Optimization did not improve (cost {result.cost:.4f} vs initial {err_initial:.4f})")
        except Exception as e:
            print(f"Full calibration failed: {e}")
            import traceback
            traceback.print_exc()

    def update_display(self):
        if self.current_frame is None:
            return

        display = self.current_frame.copy()

        # Re-project with current (possibly updated) rvec/tvec, applying flip
        if len(self.frame_points_3d) > 0:
            pts_for_proj = self.frame_points_3d.copy()
            if self.flip_y:
                pts_for_proj[:, 1] = -pts_for_proj[:, 1]
                pts_for_proj[:, 2] = -pts_for_proj[:, 2]
            pts_2d, _ = cv2.projectPoints(pts_for_proj, self.rvec, self.tvec, self.K, self.dist)
            self.frame_points_2d = pts_2d.reshape(-1, 2)

        # Draw projected markers with velocity-based coloring
        for i, (pt, name) in enumerate(zip(self.frame_points_2d, self.frame_names)):
            x, y = int(pt[0]), int(pt[1])

            if i == self.selected_idx:
                # Selected: green with ring
                cv2.circle(display, (x, y), 8, (0, 255, 0), 2)
                cv2.circle(display, (x, y), 3, (0, 255, 0), -1)
                cv2.putText(display, name.split(':')[-1], (x + 10, y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            else:
                # Velocity-based color: slow=vivid red, fast=faded pink
                vel = self.marker_velocities.get(i, 5.0)  # default mid-speed
                color = self.get_velocity_color(vel)
                radius = 4 if vel < 2.0 else 3  # slightly larger for slow markers
                cv2.circle(display, (x, y), radius, color, -1)

        # Draw calibration pairs (yellow lines)
        if self.calib_points_3d:
            calib_3d = np.array(self.calib_points_3d, dtype=np.float32)
            proj, _ = cv2.projectPoints(calib_3d, self.rvec, self.tvec, self.K, self.dist)
            proj = proj.reshape(-1, 2)

            for p_proj, p_target in zip(proj, self.calib_points_2d):
                px, py = int(p_proj[0]), int(p_proj[1])
                tx, ty = int(p_target[0]), int(p_target[1])
                cv2.line(display, (px, py), (tx, ty), (0, 255, 255), 2)
                cv2.circle(display, (tx, ty), 4, (0, 255, 255), -1)

        # Info overlay
        mode_str = "[SYNC]" if self.sync_mode else "[DIRECT]"
        flip_str = " FLIP" if self.flip_y else ""
        n_slow = sum(1 for v in self.marker_velocities.values() if v < 2.0)
        slow_info = f" | Slow: {n_slow}" if n_slow > 0 else ""
        offset_str = f"{self.time_offset:+.1f}f" if self.time_offset != 0 else "0"

        mocap_frame_str = ""
        if self.sync_mode:
            mocap_f = self.get_current_mocap_frame()
            mocap_frame_str = f" | Mocap: {mocap_f:.1f}"

        info = [
            f"{mode_str}{flip_str} Frame: {self.frame_idx}/{self.n_frames} | Offset: {offset_str}{mocap_frame_str}",
            f"Markers: {len(self.frame_points_3d)}{slow_info} | Pairs: {len(self.calib_points_3d)}",
            "[a/d]±1 [s/D]±100 [w/W]±2000 [f]stable [z]undo [t]flip",
            "[o]solvePnP [O]scipy [e]export [r]reset [q]quit"
        ]

        for i, text in enumerate(info):
            cv2.putText(display, text, (10, 30 + i * 25),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            cv2.putText(display, text, (10, 30 + i * 25),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1)

        # Resize for display
        if self.scale < 1.0:
            display = cv2.resize(display, None, fx=self.scale, fy=self.scale)

        cv2.imshow(self.window_name, display)

    def export(self, output_path):
        """Export refined camera parameters and sync info."""
        # Save camera YAML
        save_camera_yaml(output_path, self.K, self.dist, self.rvec, self.tvec)
        print(f"\nExported camera to: {output_path}")
        print(f"K:\n{self.K}")
        print(f"dist: {self.dist.flatten()}")
        print(f"rvec: {self.rvec.flatten()}")
        print(f"tvec: {self.tvec.flatten()}")

        # Save sync info JSON (same directory, _sync.json suffix)
        if output_path.endswith('.yaml'):
            json_path = output_path.replace('.yaml', '_sync.json')
        else:
            json_path = output_path + '_sync.json'

        sync_info = {
            "mode": "sync" if self.sync_mode else "direct",
            "time_offset_frames": self.time_offset,
            "flip_y": self.flip_y,
            "note": "positive = GT markers are delayed relative to video, negative = GT markers are ahead"
        }
        if self.sync_mode:
            sync_info["gopro_fps"] = self.gopro_fps
            sync_info["mocap_fps"] = self.mocap_fps
            sync_info["offset_seconds"] = self.offset_seconds
            sync_info["camera_offset"] = self.camera_offset
            sync_info["mocap_start_frame"] = self.mocap_start_frame
            sync_info["computed_mocap_frame_at_export"] = self.get_current_mocap_frame()

        with open(json_path, 'w') as f:
            json.dump(sync_info, f, indent=2)
        print(f"Exported sync info to: {json_path}")
        print(f"Time offset: {self.time_offset:+.1f} frames")

    def reset(self):
        """Reset to initial parameters."""
        self.K = self.K_init.copy()
        self.dist = self.dist_init.copy()
        self.rvec = self.rvec_init.copy()
        self.tvec = self.tvec_init.copy()
        self.calib_points_3d = []
        self.calib_points_2d = []
        self.selected_idx = -1
        self.time_offset = 0.0
        self.flip_y = False
        print("Reset to initial parameters")

    def run(self):
        self.get_frame_data()
        self.update_display()

        while True:
            key = cv2.waitKey(0) & 0xFF

            if key == ord('q'):
                break
            elif key == ord('d'):
                # Next frame
                self.frame_idx = min(self.frame_idx + 1, self.n_frames - 1)
                self.selected_idx = -1
                self.get_frame_data()
                self.update_display()
            elif key == ord('a'):
                # Prev frame
                self.frame_idx = max(self.frame_idx - 1, 0)
                self.selected_idx = -1
                self.get_frame_data()
                self.update_display()
            elif key == ord('s') or key == ord('S'):
                # Jump -100 frames
                self.frame_idx = max(self.frame_idx - 100, 0)
                self.selected_idx = -1
                self.get_frame_data()
                self.update_display()
            elif key == ord('D'):
                # Jump +100 frames
                self.frame_idx = min(self.frame_idx + 100, self.n_frames - 6)
                self.selected_idx = -1
                self.get_frame_data()
                self.update_display()
            elif key == ord('w'):
                # Jump -2000 frames
                self.frame_idx = max(self.frame_idx - 2000, 0)
                self.selected_idx = -1
                self.get_frame_data()
                self.update_display()
            elif key == ord('W'):
                # Jump +2000 frames
                self.frame_idx = min(self.frame_idx + 2000, self.n_frames - 1)
                self.selected_idx = -1
                self.get_frame_data()
                self.update_display()
            elif key == ord('f'):
                # Find stable frame (search forward)
                self.find_stable_frame()
            elif key == ord('z'):
                # Undo last calibration pair
                if self.calib_points_3d:
                    self.calib_points_3d.pop()
                    self.calib_points_2d.pop()
                    print(f"Undo. Remaining pairs: {len(self.calib_points_3d)}")
                    self.update_display()
                else:
                    print("Nothing to undo.")
            elif key == ord('t'):
                # Toggle coordinate flip
                self.flip_y = not self.flip_y
                print(f"Coordinate flip: {'ON (x,-y,-z)' if self.flip_y else 'OFF'}")
                self.get_frame_data()
                self.update_display()
            elif key == ord('o'):
                self.optimize_extrinsics()
            elif key == ord('O'):  # Shift+O
                self.optimize_full()
            elif key == ord('e'):
                self.export(args.output)
            elif key == ord('r'):
                self.reset()
                self.get_frame_data()
                self.update_display()
            elif key == ord('c'):
                self.selected_idx = -1
                self.update_display()
            elif key == ord('['):
                self.time_offset -= 1.0
                print(f"Time offset: {self.time_offset:+.1f} frames")
                self.get_frame_data()
                self.update_display()
            elif key == ord(']'):
                self.time_offset += 1.0
                print(f"Time offset: {self.time_offset:+.1f} frames")
                self.get_frame_data()
                self.update_display()
            elif key == ord(','):
                self.time_offset -= 0.5
                print(f"Time offset: {self.time_offset:+.1f} frames")
                self.get_frame_data()
                self.update_display()
            elif key == ord('.'):
                self.time_offset += 0.5
                print(f"Time offset: {self.time_offset:+.1f} frames")
                self.get_frame_data()
                self.update_display()

        self.cap.release()
        cv2.destroyAllWindows()


def main():
    global args
    parser = argparse.ArgumentParser(description='Interactive extrinsic refinement')
    parser.add_argument('--markers', required=True, help='Path to markers.npy')
    parser.add_argument('--names', help='Path to marker_names.json (optional)')
    parser.add_argument('--video', required=True, help='Path to video')
    parser.add_argument('--camera', required=True, help='Path to camera YAML')
    parser.add_argument('--output', default='refined_camera.yaml', help='Output YAML path')
    parser.add_argument('--start', type=int, default=0, help='Start frame')
    parser.add_argument('--sync', help='Path to sync_mapping.json (enables time-based sync mode)')
    parser.add_argument('--camera-offset', type=float, default=0, help='Per-camera frame offset in GoPro frames')
    parser.add_argument('--mocap-start-frame', type=int, default=0, help='Start frame for trimmed mocap data')

    args = parser.parse_args()

    # Load markers
    print(f"Loading markers: {args.markers}")
    markers = np.load(args.markers)
    print(f"  Shape: {markers.shape}")

    # Load marker names (support both formats)
    marker_names = None
    if args.names:
        candidates = [Path(args.names)]
    else:
        parent = Path(args.markers).parent
        candidates = [parent / 'marker_names.json', parent / 'markers_meta.json']

    for path in candidates:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                marker_names = data
            elif isinstance(data, dict) and 'marker_names' in data:
                marker_names = data['marker_names']
            if marker_names:
                print(f"  Names loaded from: {path} ({len(marker_names)} names)")
                break

    if marker_names is None:
        marker_names = [f'Marker_{i}' for i in range(markers.shape[1])]
        print(f"  Names: generated {len(marker_names)} default names")

    # Load sync config
    sync_config = None
    if args.sync:
        print(f"Loading sync config: {args.sync}")
        with open(args.sync) as f:
            sync_config = json.load(f)
        print(f"  offset_seconds={sync_config['offset_seconds']:.6f}, "
              f"gopro_fps={sync_config['gopro_fps']:.2f}, mocap_fps={sync_config['primecolor_fps']:.1f}")

    # Load camera
    print(f"Loading camera: {args.camera}")
    K, dist, rvec, tvec = load_camera_yaml(args.camera)
    print(f"  K:\n{K}")
    print(f"  tvec: {tvec.flatten()}")

    # Run
    mode = "SYNC" if sync_config else "DIRECT"
    print(f"\n[{mode}] Starting at frame {args.start}")
    print("Controls: [a/d] +-1, [s/D] +-100, [w/W] +-2000, [f] find stable, [z] undo, [t] flip")
    print("          [o] solvePnP, [O] scipy, [e] export, [r] reset, [q] quit")
    print("Mouse: L-click=select, R-click=place\n")

    tool = ExtrinsicRefiner(
        args.video, markers, marker_names,
        K, dist, rvec, tvec,
        start_frame=args.start,
        sync_config=sync_config,
        camera_offset=args.camera_offset,
        mocap_start_frame=args.mocap_start_frame
    )
    tool.run()


if __name__ == '__main__':
    main()
