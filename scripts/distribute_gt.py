#!/usr/bin/env python3
"""
Distribute GT data from cam19 (PrimeColor, 120fps) to each GoPro camera's gt/ folder.

Reads cam19's source GT data (skeleton, edges, polygon) at 120fps and resamples
it to each GoPro camera's timeline (~60fps), accounting for per-camera frame offsets.

Usage:
    # Single session
    python distribute_gt.py --session_dir /path/to/cameras_synced/

    # With explicit camera offsets
    python distribute_gt.py --session_dir /path/to/cameras_synced/ \
        --camera_offsets /path/to/camera_offsets.json

    # Specific cameras only
    python distribute_gt.py --session_dir /path/to/cameras_synced/ \
        --cameras cam1,cam2,cam3

    # Write to a different subfolder (for testing without overwriting)
    python distribute_gt.py --session_dir /path/to/cameras_synced/ \
        --output_suffix gt_test

Source data (auto-detected in {session_dir}/cam19/):
    skeleton_h36m.npy       (N_prime, 17, 3)     required
    *_edges.npy             (N_prime, E, 2, 3)   optional (multi-blade)
    aligned_edges.npy       (N_prime, E, 2, 3)   fallback (single blade)
    polygon_vertices.npy    (N_prime, V, 3)       optional

Output per camera ({session_dir}/camX/{gt_folder}/):
    skeleton.npy            (N_gopro, 17, 3)
    blade_edges.npy         (N_gopro, E, 2, 3)   single blade (from aligned_edges)
    <name>_edges.npy        (N_gopro, E, 2, 3)   per-blade (multi-blade)
    polygon_vertices.npy    (N_gopro, V, 3)       if source exists
    valid_mask.npy          (N_gopro,)            bool
    gt_info.json            metadata
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np


def get_video_frame_count(video_path: str) -> int:
    """Get frame count from video using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-count_frames",
        "-show_entries", "stream=nb_read_frames",
        "-print_format", "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data = json.loads(result.stdout)
        return int(data["streams"][0]["nb_read_frames"])
    except Exception:
        return -1


def get_video_fps(video_path: str) -> float:
    """Get video FPS using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-print_format", "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        data = json.loads(result.stdout)
        rate_str = data["streams"][0]["r_frame_rate"]
        num, den = rate_str.split("/")
        return float(num) / float(den)
    except Exception:
        return -1.0


def find_gopro_video(cam_dir: Path) -> Path:
    """Find the GoPro video file in a camera directory."""
    for ext in ["*.MP4", "*.mp4"]:
        videos = list(cam_dir.glob(ext))
        if videos:
            return videos[0]
    return None


def compute_frame_mapping(n_output: int, gopro_fps: float, primecolor_fps: float,
                          offset_seconds: float, n_primecolor: int,
                          camera_offset_frames: float = 0.0) -> np.ndarray:
    """
    Compute per-frame GoPro → PrimeColor mapping directly from timing parameters.

    For each GoPro frame g:
        t_gopro = g / gopro_fps
        t_prime = t_gopro - offset_seconds - camera_offset / gopro_fps
        prime_frame = round(t_prime * primecolor_fps)

    Args:
        n_output: Number of GoPro output frames
        gopro_fps: GoPro frame rate (~60fps)
        primecolor_fps: PrimeColor frame rate (120fps)
        offset_seconds: Time offset from sync_mapping.json
        n_primecolor: Total PrimeColor frames (for bounds checking)
        camera_offset_frames: Per-camera offset in GoPro frame units

    Returns:
        np.ndarray of shape (n_output,) with PrimeColor frame indices.
        -1 means no valid PrimeColor data for that GoPro frame.
    """
    gopro_indices = np.arange(n_output, dtype=np.float64)

    # GoPro frame → time in GoPro timeline
    t_gopro = gopro_indices / gopro_fps

    # Apply sync offset + per-camera offset (convert camera offset to seconds)
    # Note: camera_offset is ADDED (matches refine_extrinsics.py convention:
    #   f_mocap += camera_offset * (mocap_fps / gopro_fps))
    t_prime = t_gopro - offset_seconds + camera_offset_frames / gopro_fps

    # Convert to PrimeColor frame index (nearest frame)
    prime_frames = np.round(t_prime * primecolor_fps).astype(np.int64)

    # Mark out-of-bounds as -1
    out_of_bounds = (prime_frames < 0) | (prime_frames >= n_primecolor)
    prime_frames[out_of_bounds] = -1

    return prime_frames


def resample_data(source: np.ndarray, mapping: np.ndarray, n_output: int) -> tuple:
    """
    Resample source data (PrimeColor 120fps) to GoPro timeline using precomputed mapping.

    Args:
        source: Source array, first dimension is PrimeColor frames
        mapping: GoPro→PrimeColor frame mapping (from compute_frame_mapping)
        n_output: Number of output GoPro frames

    Returns:
        (resampled_data, valid_mask)
    """
    n_source = source.shape[0]
    out_shape = (n_output,) + source.shape[1:]
    output = np.full(out_shape, np.nan, dtype=np.float32)
    valid_mask = np.zeros(n_output, dtype=bool)

    # Vectorized: get valid indices
    valid = (mapping >= 0) & (mapping < n_source)
    valid_gopro = np.where(valid)[0]
    valid_prime = mapping[valid]

    output[valid_gopro] = source[valid_prime].astype(np.float32)
    valid_mask[valid_gopro] = True

    return output, valid_mask


def distribute_gt(session_dir: str, camera_offsets_path: str = None,
                  cameras: list = None, output_suffix: str = "gt",
                  force: bool = False) -> bool:
    """
    Distribute GT data from cam19 to each GoPro camera.

    Args:
        session_dir: Path to cameras_synced/ directory
        camera_offsets_path: Path to camera_offsets.json (optional)
        cameras: List of camera names to process (optional, auto-detect)
        output_suffix: Name of the output subfolder (default: "gt")
        force: Overwrite existing gt/ folders
    """
    session_dir = Path(session_dir)
    cam19_dir = session_dir / "cam19"

    print("=" * 70)
    print("  GT Distribution: cam19 → per-camera gt/ folders")
    print("=" * 70)
    print(f"  Session: {session_dir}")

    # --- Load source GT data from cam19 ---
    skeleton_path = cam19_dir / "skeleton_h36m.npy"
    polygon_path = cam19_dir / "polygon_vertices.npy"

    if not skeleton_path.exists():
        print(f"  ERROR: {skeleton_path} not found")
        return False

    skeleton_src = np.load(skeleton_path)
    print(f"  Skeleton: {skeleton_path.name} {skeleton_src.shape}")

    # Detect blade edge files: prefer named *_edges.npy, fall back to aligned_edges.npy
    blade_sources = {}  # name -> (path, array)
    named_edges = sorted([
        p for p in cam19_dir.glob("*_edges.npy")
        if p.name != "aligned_edges.npy"
    ])
    if named_edges:
        for p in named_edges:
            arr = np.load(p)
            blade_sources[p.name] = (p, arr)
            print(f"  Blade:    {p.name} {arr.shape}")
    else:
        edges_path = cam19_dir / "aligned_edges.npy"
        if edges_path.exists():
            arr = np.load(edges_path)
            blade_sources["blade_edges.npy"] = (edges_path, arr)
            print(f"  Edges:    {edges_path.name} {arr.shape} (single blade)")

    polygon_src = None
    if polygon_path.exists():
        polygon_src = np.load(polygon_path)
        print(f"  Polygon:  {polygon_path.name} {polygon_src.shape}")

    n_prime_frames = skeleton_src.shape[0]

    # --- Load sync mapping ---
    sync_mapping_path = cam19_dir / "sync_mapping.json"
    if not sync_mapping_path.exists():
        print(f"  ERROR: {sync_mapping_path} not found")
        return False

    with open(sync_mapping_path) as f:
        sync_mapping = json.load(f)

    offset_seconds = sync_mapping["offset_seconds"]
    gopro_fps = sync_mapping.get("gopro_fps", sync_mapping.get("target_fps", 60.0))
    primecolor_fps = sync_mapping.get("primecolor_fps", 120.0)
    n_output_base = sync_mapping.get("output_frames", sync_mapping.get("gopro_frames", 0))

    print(f"  Sync: offset={offset_seconds:.4f}s, gopro_fps={gopro_fps:.2f}, "
          f"prime_fps={primecolor_fps:.1f}")
    print(f"  Frames: {n_prime_frames} prime → {n_output_base} gopro (base)")

    # --- Load camera offsets ---
    camera_offsets = {}
    if camera_offsets_path and Path(camera_offsets_path).exists():
        with open(camera_offsets_path) as f:
            camera_offsets = json.load(f)
        print(f"  Camera offsets: {camera_offsets_path}")
    elif (session_dir / "camera_offsets.json").exists():
        with open(session_dir / "camera_offsets.json") as f:
            camera_offsets = json.load(f)
        print(f"  Camera offsets: camera_offsets.json (auto-detected)")
    else:
        print("  Camera offsets: none (all cameras default to 0)")

    # --- Determine cameras to process ---
    if cameras:
        cam_list = cameras
    else:
        cam_list = sorted([
            d.name for d in session_dir.iterdir()
            if d.is_dir() and d.name.startswith("cam") and d.name != "cam19"
        ])

    print(f"  Cameras: {len(cam_list)} ({', '.join(cam_list)})")
    print()

    # --- Process each camera ---
    success = 0
    skip = 0
    fail = 0

    for cam_name in cam_list:
        cam_dir = session_dir / cam_name
        gt_dir = cam_dir / output_suffix

        if not cam_dir.exists():
            print(f"  [{cam_name}] Directory not found, skipping")
            fail += 1
            continue

        if gt_dir.exists() and not force:
            existing = list(gt_dir.glob("*.npy"))
            if existing:
                print(f"  [{cam_name}] gt/ already exists ({len(existing)} files), skipping")
                skip += 1
                continue

        # Determine GoPro frame count for this camera
        n_gopro_frames = n_output_base

        # Get camera offset
        cam_offset = float(camera_offsets.get(cam_name, 0))

        # Build per-camera frame mapping (accounts for camera offset)
        mapping = compute_frame_mapping(
            n_output=n_gopro_frames,
            gopro_fps=gopro_fps,
            primecolor_fps=primecolor_fps,
            offset_seconds=offset_seconds,
            n_primecolor=n_prime_frames,
            camera_offset_frames=cam_offset,
        )

        # Resample skeleton
        skel_out, valid_mask = resample_data(skeleton_src, mapping, n_gopro_frames)

        # Resample blade edges (one or more blade files)
        blade_outputs = {}  # output_name -> array
        for out_name, (src_path, src_arr) in blade_sources.items():
            resampled, _ = resample_data(src_arr, mapping, n_gopro_frames)
            blade_outputs[out_name] = resampled

        # Resample polygon (if available)
        polygon_out = None
        if polygon_src is not None:
            polygon_out, _ = resample_data(polygon_src, mapping, n_gopro_frames)

        # Compute valid range
        valid_indices = np.where(valid_mask)[0]
        valid_start = int(valid_indices[0]) if len(valid_indices) > 0 else -1
        valid_end = int(valid_indices[-1]) if len(valid_indices) > 0 else -1
        valid_count = int(valid_mask.sum())

        # Save
        gt_dir.mkdir(parents=True, exist_ok=True)

        np.save(gt_dir / "skeleton.npy", skel_out)
        np.save(gt_dir / "valid_mask.npy", valid_mask)

        for out_name, out_arr in blade_outputs.items():
            np.save(gt_dir / out_name, out_arr)

        if polygon_out is not None:
            np.save(gt_dir / "polygon_vertices.npy", polygon_out)

        # Save metadata
        blade_files = [
            f"cam19/{src_path.name}"
            for src_path, _ in blade_sources.values()
        ] if blade_sources else None
        gt_info = {
            "n_frames": n_gopro_frames,
            "valid_start": valid_start,
            "valid_end": valid_end,
            "valid_count": valid_count,
            "gopro_fps": gopro_fps,
            "mocap_fps": primecolor_fps,
            "video_fps": gopro_fps,
            "offset_seconds": offset_seconds,
            "frame_offset": cam_offset,
            "source_skeleton": "cam19/skeleton_h36m.npy",
            "blade_files": blade_files,
            "has_polygon": polygon_src is not None,
        }
        with open(gt_dir / "gt_info.json", "w") as f:
            json.dump(gt_info, f, indent=2)

        print(f"  [{cam_name}] offset={cam_offset:+.1f} → "
              f"valid {valid_start}-{valid_end} ({valid_count}/{n_gopro_frames})")
        success += 1

    print()
    print("=" * 70)
    print(f"  Done: {success} success, {skip} skipped, {fail} failed")
    print("=" * 70)
    return fail == 0


def main():
    parser = argparse.ArgumentParser(
        description="Distribute GT data from cam19 to per-camera gt/ folders"
    )
    parser.add_argument(
        "--session_dir", required=True,
        help="Path to cameras_synced/ directory"
    )
    parser.add_argument(
        "--camera_offsets",
        help="Path to camera_offsets.json (optional, auto-detected in session_dir)"
    )
    parser.add_argument(
        "--cameras",
        help="Comma-separated camera list (default: all cam* except cam19)"
    )
    parser.add_argument(
        "--output_suffix", default="gt",
        help="Output subfolder name (default: gt)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing gt/ folders"
    )

    args = parser.parse_args()

    cameras = args.cameras.split(",") if args.cameras else None

    ok = distribute_gt(
        session_dir=args.session_dir,
        camera_offsets_path=args.camera_offsets,
        cameras=cameras,
        output_suffix=args.output_suffix,
        force=args.force,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
