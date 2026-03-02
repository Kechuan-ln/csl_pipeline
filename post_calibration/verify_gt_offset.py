#!/usr/bin/env python3
"""
GT Temporal Offset Verification Tool (Video Playback Mode)

Pre-loads a short video clip and 3D GT data, then plays them as a video
with skeleton/blade overlay. User adjusts the per-camera temporal offset
and replays until the overlay aligns with the person in the video.

Usage:
    # Verify cam1 starting at 60 seconds, 10-second clip
    python verify_gt_offset.py \
        --session_dir /Volumes/FastACIS/csl_11_5/synced/P4_1_sync/cameras_synced/ \
        --camera cam1 --start 60 --duration 10

    # Start at frame 3000 (instead of seconds)
    python verify_gt_offset.py \
        --session_dir /path/to/cameras_synced/ \
        --camera cam3 --start_frame 3000 --duration 10

Controls (while paused):
    Space     : Play/Replay clip from beginning
    p         : Play from current frame
    a/d       : Step +/-1 frame
    s/D       : Step +/-10 frames
    w/W       : Step +/-100 frames
    [/]       : Offset +/-1.0 frame
    ,/.       : Offset +/-0.5 frame
    e         : Save offset + redistribute GT for this camera
    q         : Quit
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np


# H36M 17-joint skeleton topology
# Joint order: 0=Hip, 1=RHip, 2=RKnee, 3=RAnkle, 4=LHip, 5=LKnee, 6=LAnkle,
#              7=Spine, 8=Thorax, 9=Neck, 10=Head,
#              11=LShoulder, 12=LElbow, 13=LWrist, 14=RShoulder, 15=RElbow, 16=RWrist
H36M_BONES = [
    (0, 1), (1, 2), (2, 3),          # right leg
    (0, 4), (4, 5), (5, 6),          # left leg
    (0, 7), (7, 8), (8, 9), (9, 10), # spine
    (8, 11), (11, 12), (12, 13),     # left arm
    (8, 14), (14, 15), (15, 16),     # right arm
]

SKELETON_COLOR = (0, 255, 0)          # green
BLADE_FILL_ALPHA = 0.35

# Per-blade color palette: (edge_color, fill_color)
BLADE_COLORS = [
    ((0, 255, 255), (255, 180, 0)),   # yellow edges, orange fill
    ((255, 255, 0), (0, 180, 255)),   # cyan edges, blue fill
    ((255, 0, 255), (180, 0, 255)),   # magenta edges, purple fill
    ((0, 255, 128), (0, 200, 100)),   # green edges, teal fill
]


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


class GTOffsetPlayer:
    """Pre-load a video clip, overlay projected skeleton, play back for offset tuning."""

    def __init__(self, session_dir, camera, start_sec=60.0, duration=10.0,
                 camera_yaml=None, start_frame=None):
        self.session_dir = Path(session_dir)
        self.camera = camera
        self.cam_dir = self.session_dir / camera

        # --- Video ---
        self.video_path = self._find_video()
        self.cap = cv2.VideoCapture(str(self.video_path))
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.video_path}")
        self.vid_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.vid_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.n_video_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.video_fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.scale = min(1.0, 1920 / self.vid_w)
        self.disp_w = int(self.vid_w * self.scale)
        self.disp_h = int(self.vid_h * self.scale)
        print(f"Video: {self.video_path.name} "
              f"({self.vid_w}x{self.vid_h}, {self.n_video_frames} frames, "
              f"{self.video_fps:.2f} fps)")
        print(f"Display: {self.disp_w}x{self.disp_h} (scale={self.scale:.2f})")

        # --- Camera params ---
        if camera_yaml:
            yaml_path = Path(camera_yaml)
        else:
            yaml_path = self.session_dir / "individual_cam_params" / f"{camera}.yaml"
        self.K, self.dist, self.rvec, self.tvec = load_camera_yaml(yaml_path)
        # Pre-scale K for display resolution
        self.K_disp = self.K.copy()
        self.K_disp[0, :] *= self.scale
        self.K_disp[1, :] *= self.scale
        print(f"Camera: {yaml_path}")

        # --- Skeleton GT (120fps, from cam19/ symlink) ---
        skel_path = self.session_dir / "cam19" / "skeleton_h36m.npy"
        self.skeleton = np.load(str(skel_path))
        self.n_mocap = self.skeleton.shape[0]
        print(f"Skeleton: {skel_path.name} {self.skeleton.shape}")

        # --- Blade edges (optional, supports multiple blades) ---
        cam19 = self.session_dir / "cam19"
        self.blade_edges = {}  # name -> array
        named_edges = sorted([
            p for p in cam19.glob("*_edges.npy")
            if p.name != "aligned_edges.npy"
        ])
        if named_edges:
            for p in named_edges:
                name = p.name.replace("_edges.npy", "")
                self.blade_edges[name] = np.load(str(p))
                print(f"Blade: {p.name} {self.blade_edges[name].shape}")
        else:
            edges_path = cam19 / "aligned_edges.npy"
            if edges_path.exists():
                self.blade_edges["blade"] = np.load(str(edges_path))
                print(f"Blade: {edges_path.name} {self.blade_edges['blade'].shape}")

        # --- Sync mapping ---
        sync_path = self.session_dir / "cam19" / "sync_mapping.json"
        with open(sync_path) as f:
            sync = json.load(f)
        self.gopro_fps = sync.get("gopro_fps", sync.get("target_fps", 60.0))
        self.mocap_fps = sync.get("primecolor_fps", 120.0)
        self.offset_seconds = sync["offset_seconds"]
        print(f"Sync: offset={self.offset_seconds:.4f}s, "
              f"gopro={self.gopro_fps:.2f}fps, mocap={self.mocap_fps:.1f}fps")

        # --- Camera offset ---
        self.camera_offset = 0.0
        self.offsets_path = self.session_dir / "camera_offsets.json"
        if self.offsets_path.exists():
            with open(self.offsets_path) as f:
                offsets = json.load(f)
            self.camera_offset = float(offsets.get(camera, 0.0))
        print(f"Camera offset: {self.camera_offset:+.1f} frames")

        # --- Clip range ---
        if start_frame is not None:
            self.start_frame = max(0, min(start_frame, self.n_video_frames - 1))
        else:
            self.start_frame = max(0, int(start_sec * self.gopro_fps))
        self.clip_len = min(
            int(duration * self.gopro_fps),
            self.n_video_frames - self.start_frame,
        )
        if self.clip_len <= 0:
            raise ValueError("No frames to load (start exceeds video length)")

        # --- Pre-load ---
        self._preload_frames()

        # --- State ---
        self.clip_idx = 0

        # --- Window (no trackbars - they crash on macOS ARM64 + Python 3.8) ---
        session_name = self.session_dir.parent.name.replace("_sync", "")
        self.win = f"GT Offset: {camera} | {session_name}"
        cv2.namedWindow(self.win, cv2.WINDOW_AUTOSIZE)

        print(f"\nClip: frames {self.start_frame}"
              f"~{self.start_frame + self.clip_len - 1} "
              f"({self.clip_len} frames, {self.clip_len / self.gopro_fps:.1f}s)")
        mem_gb = self.clip_len * self.disp_w * self.disp_h * 3 / 1e9
        print(f"Memory: ~{mem_gb:.1f} GB")
        print()
        self._print_controls()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _find_video(self):
        for pat in ["*.MP4", "*.mp4"]:
            videos = list(self.cam_dir.glob(pat))
            if videos:
                return videos[0]
        raise FileNotFoundError(f"No video in {self.cam_dir}")

    def _preload_frames(self):
        """Decode clip frames into RAM at display resolution."""
        print(f"\nPreloading {self.clip_len} frames...", end="", flush=True)
        t0 = time.time()
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.start_frame)
        self.frames = []
        for i in range(self.clip_len):
            ret, frame = self.cap.read()
            if not ret:
                break
            if self.scale < 1.0:
                frame = cv2.resize(frame, (self.disp_w, self.disp_h),
                                   interpolation=cv2.INTER_AREA)
            self.frames.append(frame)
            if (i + 1) % 100 == 0:
                print(f"\rPreloading {i + 1}/{self.clip_len}...",
                      end="", flush=True)
        dt = time.time() - t0
        print(f"\rPreloaded {len(self.frames)} frames in {dt:.1f}s")
        self.clip_len = len(self.frames)

    def _print_controls(self):
        print("Controls:")
        print("  Space : Play/Replay from start    p : Play from current")
        print("  a/d   : +/-1 frame    s/D : +/-10    w/W : +/-100")
        print("  [/]   : Offset +/-1.0    ,/. : +/-0.5")
        print("  e     : Save + redistribute GT    q : Quit")

    # (trackbars removed - they crash on macOS ARM64 + Python 3.8 OpenCV Cocoa backend)

    # ------------------------------------------------------------------
    # Frame mapping & projection
    # ------------------------------------------------------------------

    def get_mocap_frame(self, gopro_frame):
        """GoPro frame index -> mocap frame index (with current offset)."""
        t_gopro = gopro_frame / self.gopro_fps
        t_prime = t_gopro - self.offset_seconds + self.camera_offset / self.gopro_fps
        return round(t_prime * self.mocap_fps)

    def project_to_display(self, pts_3d_mm):
        """Project 3D points (mm) to display-resolution 2D pixel coordinates."""
        pts_m = pts_3d_mm.astype(np.float64) / 1000.0
        pts_2d, _ = cv2.projectPoints(pts_m, self.rvec, self.tvec,
                                       self.K_disp, self.dist)
        return pts_2d.reshape(-1, 2)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw_skeleton(self, frame, skel_3d):
        """Draw H36M skeleton overlay. skel_3d: (17, 3) in mm."""
        valid = ~np.isnan(skel_3d).any(axis=1)
        if valid.sum() < 2:
            return
        pts_2d = self.project_to_display(skel_3d)

        for (i, j) in H36M_BONES:
            if valid[i] and valid[j]:
                p1 = tuple(pts_2d[i].astype(int))
                p2 = tuple(pts_2d[j].astype(int))
                cv2.line(frame, p1, p2, SKELETON_COLOR, 2)

        for i in range(17):
            if valid[i]:
                pt = tuple(pts_2d[i].astype(int))
                cv2.circle(frame, pt, 4, SKELETON_COLOR, -1)

    def draw_blade_edges(self, frame, edges_3d, edge_color, fill_color):
        """Draw blade edges with semi-transparent fill. edges_3d: (E, 2, 3) in mm."""
        E = edges_3d.shape[0]
        edges_flat = edges_3d.reshape(-1, 3)  # (E*2, 3)

        # Project all endpoints at once
        valid_flat = ~np.isnan(edges_flat).any(axis=1)
        pts_2d_flat = np.full((E * 2, 2), np.nan, dtype=np.float32)
        if valid_flat.any():
            valid_pts = edges_flat[valid_flat] / 1000.0
            proj, _ = cv2.projectPoints(valid_pts.astype(np.float64),
                                        self.rvec, self.tvec,
                                        self.K_disp, self.dist)
            pts_2d_flat[valid_flat] = proj.reshape(-1, 2)

        edges_2d = pts_2d_flat.reshape(E, 2, 2)  # (E, 2endpoints, xy)
        valid = ~np.any(np.isnan(edges_2d), axis=(1, 2))

        if valid.sum() < 2:
            return

        left_2d = edges_2d[:, 0, :]   # (E, 2)
        right_2d = edges_2d[:, 1, :]  # (E, 2)

        # Semi-transparent filled quads between consecutive edges
        overlay = frame.copy()
        for i in range(E - 1):
            if valid[i] and valid[i + 1]:
                pts = np.array([
                    left_2d[i], right_2d[i],
                    right_2d[i + 1], left_2d[i + 1],
                ], dtype=np.int32)
                cv2.fillPoly(overlay, [pts], fill_color)
        cv2.addWeighted(overlay, BLADE_FILL_ALPHA, frame,
                        1 - BLADE_FILL_ALPHA, 0, frame)

        # Draw cross-link edges
        for i in range(E):
            if valid[i]:
                p1 = tuple(left_2d[i].astype(int))
                p2 = tuple(right_2d[i].astype(int))
                cv2.line(frame, p1, p2, edge_color, 2)

        # Draw left/right edge curves
        valid_left = left_2d[valid].astype(np.int32).reshape(-1, 1, 2)
        valid_right = right_2d[valid].astype(np.int32).reshape(-1, 1, 2)
        if len(valid_left) > 1:
            cv2.polylines(frame, [valid_left], False, edge_color, 2)
            cv2.polylines(frame, [valid_right], False, edge_color, 2)

    def draw_hud(self, frame, gopro_frame, mocap_frame):
        """Draw frame info overlay + progress bar."""
        in_range = 0 <= mocap_frame < self.n_mocap
        status = "VALID" if in_range else "OUT OF RANGE"
        s_col = (0, 255, 0) if in_range else (0, 0, 255)

        blade_str = ""
        if self.blade_edges:
            blade_names = list(self.blade_edges.keys())
            blade_str = "  Blades: " + ", ".join(blade_names)

        lines = [
            (f"GoPro: {gopro_frame}  Mocap: {mocap_frame}  "
             f"Offset: {self.camera_offset:+.1f}", (255, 255, 255)),
            (f"[{status}]  {self.camera}{blade_str}", s_col),
        ]

        for i, (text, color) in enumerate(lines):
            y = 28 + i * 26
            cv2.putText(frame, text, (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3)
            cv2.putText(frame, text, (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 1)

        # Progress bar
        pct = self.clip_idx / max(1, self.clip_len - 1)
        bar_w = self.disp_w - 20
        bar_y = self.disp_h - 12
        cv2.rectangle(frame, (10, bar_y), (10 + bar_w, bar_y + 6),
                      (60, 60, 60), -1)
        cv2.rectangle(frame, (10, bar_y), (10 + int(bar_w * pct), bar_y + 6),
                      (0, 200, 200), -1)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_frame(self, clip_idx):
        """Build display frame: video + skeleton overlay + HUD."""
        frame = self.frames[clip_idx].copy()
        gopro_frame = self.start_frame + clip_idx
        mocap_frame = self.get_mocap_frame(gopro_frame)

        if 0 <= mocap_frame < self.n_mocap:
            skel = self.skeleton[mocap_frame]
            self.draw_skeleton(frame, skel)
            for idx, (name, edges_arr) in enumerate(self.blade_edges.items()):
                if mocap_frame < len(edges_arr):
                    colors = BLADE_COLORS[idx % len(BLADE_COLORS)]
                    self.draw_blade_edges(frame, edges_arr[mocap_frame],
                                          colors[0], colors[1])

        self.draw_hud(frame, gopro_frame, mocap_frame)
        return frame

    def _show_current(self):
        """Render and display the current clip frame."""
        rendered = self.render_frame(self.clip_idx)
        cv2.imshow(self.win, rendered)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play_clip(self, from_idx=0):
        """Play clip at video framerate. Returns key that interrupted, or -1."""
        delay_ms = max(1, int(1000 / self.gopro_fps))
        for i in range(from_idx, self.clip_len):
            self.clip_idx = i
            rendered = self.render_frame(i)
            cv2.imshow(self.win, rendered)
            key = cv2.waitKey(delay_ms) & 0xFF
            if key == ord(' ') or key == ord('q'):
                return key
        return -1

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_and_redistribute(self):
        """Save offset to camera_offsets.json and re-run distribute_gt.py."""
        # Save offset
        offsets = {}
        if self.offsets_path.exists():
            with open(self.offsets_path) as f:
                offsets = json.load(f)
        offsets[self.camera] = self.camera_offset
        with open(self.offsets_path, 'w') as f:
            json.dump(offsets, f, indent=2, sort_keys=True)
        print(f"\nSaved {self.camera}={self.camera_offset:+.1f} "
              f"-> {self.offsets_path}")
        print(f"All offsets: {json.dumps(offsets, sort_keys=True)}")

        # Redistribute GT for this camera
        dist_script = (Path(__file__).resolve().parent.parent
                       / "scripts" / "distribute_gt.py")
        if dist_script.exists():
            cmd = [
                sys.executable, str(dist_script),
                "--session_dir", str(self.session_dir),
                "--cameras", self.camera,
                "--camera_offsets", str(self.offsets_path),
                "--force",
            ]
            print(f"Redistributing GT for {self.camera}...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"GT redistributed for {self.camera}")
            else:
                print(f"WARNING: distribute_gt.py failed:\n{result.stderr}")
        else:
            print(f"distribute_gt.py not found at {dist_script}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        """Main event loop: play, adjust offset, replay."""
        # Initial play
        print("\nPlaying clip...")
        result = self.play_clip(0)
        if result == ord('q'):
            self.cap.release()
            cv2.destroyAllWindows()
            return

        # Paused interaction loop (poll at ~20Hz for key responsiveness)
        self._show_current()
        while True:
            key = cv2.waitKey(50) & 0xFF
            if key == 255:
                continue

            if key == ord('q'):
                break

            elif key == ord(' '):
                self.clip_idx = 0

                result = self.play_clip(0)
                if result == ord('q'):
                    break
                self._show_current()

            elif key == ord('p'):
                result = self.play_clip(self.clip_idx)
                if result == ord('q'):
                    break
                self._show_current()

            elif key == ord('d'):
                self.clip_idx = min(self.clip_idx + 1, self.clip_len - 1)

                self._show_current()

            elif key == ord('a'):
                self.clip_idx = max(self.clip_idx - 1, 0)

                self._show_current()

            elif key == ord('D'):
                self.clip_idx = min(self.clip_idx + 10, self.clip_len - 1)

                self._show_current()

            elif key == ord('s'):
                self.clip_idx = max(self.clip_idx - 10, 0)

                self._show_current()

            elif key == ord('W'):
                self.clip_idx = min(self.clip_idx + 100, self.clip_len - 1)

                self._show_current()

            elif key == ord('w'):
                self.clip_idx = max(self.clip_idx - 100, 0)

                self._show_current()

            elif key == ord(']'):
                self.camera_offset += 1.0
                print(f"Offset: {self.camera_offset:+.1f}")

                self._show_current()

            elif key == ord('['):
                self.camera_offset -= 1.0
                print(f"Offset: {self.camera_offset:+.1f}")

                self._show_current()

            elif key == ord('.'):
                self.camera_offset += 0.5
                print(f"Offset: {self.camera_offset:+.1f}")

                self._show_current()

            elif key == ord(','):
                self.camera_offset -= 0.5
                print(f"Offset: {self.camera_offset:+.1f}")

                self._show_current()

            elif key == ord('e'):
                self.save_and_redistribute()

        self.cap.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(
        description="GT Temporal Offset Verification (Video Playback)")
    parser.add_argument("--session_dir", required=True,
                        help="Path to cameras_synced/ directory")
    parser.add_argument("--camera", required=True,
                        help="Camera name (e.g., cam1)")
    parser.add_argument("--start", type=float, default=60.0,
                        help="Clip start in seconds (default: 60)")
    parser.add_argument("--start_frame", type=int, default=None,
                        help="Clip start in frame index (overrides --start)")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="Clip duration in seconds (default: 10)")
    parser.add_argument("--camera_yaml",
                        help="Override camera YAML path")

    args = parser.parse_args()

    player = GTOffsetPlayer(
        session_dir=args.session_dir,
        camera=args.camera,
        start_sec=args.start,
        duration=args.duration,
        camera_yaml=args.camera_yaml,
        start_frame=args.start_frame,
    )
    player.run()


if __name__ == "__main__":
    main()
