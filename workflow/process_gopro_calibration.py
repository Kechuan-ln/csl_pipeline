#!/usr/bin/env python3
"""
Complete GoPro calibration pipeline: organize → sync → calibrate → distribute GT.

This workflow processes GoPro data from organized videos through to final GT distribution:
  1. GoPro QR synchronization (all sessions)
  2. PrimeColor synchronization (all sessions)
  3. Frame extraction (calibration session only)
  4. Stable frame detection (calibration session only)
  5. 17-camera joint calibration (calibration session only)
  6. [INTERACTIVE] cam19 refinement (all sessions, requires user)
  7. Individual camera YAML generation (all sessions)
  8. GT distribution (all sessions)

Two modes:
  - calibration: Full pipeline on one session to establish shared calibration.json
  - regular: Use shared calibration for other sessions (only cam19 + GT)

Prerequisites:
  - GoPro videos organized in per-session structure (use organize_gopro_videos.py)
  - Mocap data processed (use process_mocap_session.py)
  - .mcal file available (for cam19_initial.yaml generation)

Usage:
    # Calibration session (e.g., P7_2) - establishes shared calibration.json
    python workflow/process_gopro_calibration.py \
        --organized_dir /Volumes/FastACIS/csl_11_5/organized \
        --mocap_dir /Volumes/T7/csl \
        --output_dir /Volumes/FastACIS/csl_11_5/synced \
        --mcal_file /Volumes/T7/csl/Cal_2026-02-01.mcal \
        --anchor_video /Volumes/FastACIS/csl_11_5/organized/qr_sync.mp4 \
        --calibration_session P7_2 \
        --start_time 334 \
        --duration 292 \
        --sessions P7_1 P7_2 P7_3 P7_4 P7_5

    # After cam19 refinement, finalize the calibration session
    python workflow/process_gopro_calibration.py \
        --organized_dir /Volumes/FastACIS/csl_11_5/organized \
        --mocap_dir /Volumes/T7/csl \
        --output_dir /Volumes/FastACIS/csl_11_5/synced \
        --calibration_session P7_2 \
        --sessions P7_2 \
        --finalize

    # Process other sessions using shared calibration
    python workflow/process_gopro_calibration.py \
        --organized_dir /Volumes/FastACIS/csl_11_5/organized \
        --mocap_dir /Volumes/T7/csl \
        --output_dir /Volumes/FastACIS/csl_11_5/synced \
        --anchor_video /Volumes/FastACIS/csl_11_5/organized/qr_sync.mp4 \
        --calibration_session P7_2 \
        --sessions P7_1 P7_3 P7_4 P7_5 \
        --skip_calibration

After running in calibration mode, the script will pause and prompt you to run
post_calibration/refine_extrinsics.py interactively for cam19 refinement.
Then run again with --finalize to complete the pipeline.
"""

import os
import sys
import argparse
import subprocess
import shutil
import json
from pathlib import Path
from typing import List, Optional

# Add csl_pipeline paths for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSL_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(CSL_ROOT, "scripts"))
sys.path.insert(0, os.path.join(CSL_ROOT, "sync"))

# Terminal colors
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_header(msg):
    """Print section header."""
    print(f"\n{Colors.HEADER}{'='*70}")
    print(f"{msg}")
    print(f"{'='*70}{Colors.ENDC}\n")


def print_step(step_num, total_steps, msg):
    """Print step progress."""
    print(f"\n{Colors.OKBLUE}[Step {step_num}/{total_steps}] {msg}{Colors.ENDC}")


def print_success(msg):
    """Print success message."""
    print(f"{Colors.OKGREEN}✓ {msg}{Colors.ENDC}")


def print_warning(msg):
    """Print warning message."""
    print(f"{Colors.WARNING}⚠ {msg}{Colors.ENDC}")


def print_error(msg):
    """Print error message."""
    print(f"{Colors.FAIL}✗ {msg}{Colors.ENDC}")


def run_command(cmd, description, check=True):
    """Run shell command with logging."""
    print(f"  Running: {description}")
    print(f"  Command: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=False)

    if check and result.returncode != 0:
        print_error(f"{description} failed with exit code {result.returncode}")
        sys.exit(1)

    return result.returncode == 0


def check_file_exists(filepath, required=True):
    """Check if file exists."""
    if Path(filepath).exists():
        print_success(f"Found: {filepath}")
        return True
    else:
        if required:
            print_error(f"Required file not found: {filepath}")
            sys.exit(1)
        else:
            print_warning(f"Optional file not found: {filepath}")
            return False


def check_dir_exists(dirpath, create=False):
    """Check if directory exists, optionally create it."""
    path = Path(dirpath)
    if path.exists():
        print_success(f"Found: {dirpath}")
        return True
    else:
        if create:
            path.mkdir(parents=True, exist_ok=True)
            print_success(f"Created: {dirpath}")
            return True
        else:
            print_error(f"Directory not found: {dirpath}")
            sys.exit(1)


def step1_gopro_sync(organized_dir, output_dir, anchor_video, sessions):
    """Step 1: Synchronize GoPro videos using QR anchor."""
    print_step(1, 8, "GoPro QR Synchronization")

    # Check anchor video
    check_file_exists(anchor_video)

    # Sync each session
    for session in sessions:
        session_input = Path(organized_dir) / session
        session_output = Path(output_dir) / f"{session}_sync"

        # Skip if already synced
        meta_file = session_output / "cameras_synced" / "meta_info.json"
        if meta_file.exists():
            print_success(f"{session}: Already synced (meta_info.json exists)")
            continue

        print(f"\n  Syncing {session}...")

        cmd = [
            "python", os.path.join(CSL_ROOT, "sync", "sync_gopro_qr_fast.py"),
            "--input_dir", str(session_input),
            "--output_dir", str(session_output),
            "--anchor_video", anchor_video,
            "--verify"
        ]

        run_command(cmd, f"GoPro sync for {session}")

    print_success("All GoPro sessions synchronized")


def step2_primecolor_sync(mocap_dir, output_dir, sessions):
    """Step 2: Synchronize PrimeColor videos to GoPro timeline."""
    print_step(2, 8, "PrimeColor Synchronization")

    for session in sessions:
        session_mocap = Path(mocap_dir) / session
        session_synced = Path(output_dir) / f"{session}_sync" / "cameras_synced"

        # Check if PrimeColor video exists
        primecolor_input = session_mocap / "primecolor.mp4"
        if not primecolor_input.exists():
            print_warning(f"{session}: primecolor.mp4 not found, skipping")
            continue

        # Check if already synced
        primecolor_output = session_synced / "cam19" / "primecolor_synced.mp4"
        sync_mapping = session_synced / "cam19" / "sync_mapping.json"
        if primecolor_output.exists() and sync_mapping.exists():
            print_success(f"{session}: Already synced")
            continue

        print(f"\n  Syncing {session}...")

        # Read GoPro meta_info
        meta_file = session_synced / "meta_info.json"
        check_file_exists(meta_file)

        cmd = [
            "python", os.path.join(CSL_ROOT, "sync", "sync_primecolor_to_gopro_precise.py"),
            "--primecolor", str(primecolor_input),
            "--gopro_meta", str(meta_file),
            "--output_dir", str(session_synced / "cam19")
        ]

        run_command(cmd, f"PrimeColor sync for {session}")

    print_success("All PrimeColor videos synchronized")


def step3_create_cam19_initial(mcal_file, calibration_session, output_dir):
    """Step 3: Create cam19_initial.yaml from .mcal file."""
    print_step(3, 8, "Create cam19_initial.yaml")

    session_synced = Path(output_dir) / f"{calibration_session}_sync" / "cameras_synced"
    output_yaml = session_synced / "cam19_initial.yaml"

    # Skip if already exists
    if output_yaml.exists():
        print_success("cam19_initial.yaml already exists")
        return

    check_file_exists(mcal_file)

    cmd = [
        "python", os.path.join(CSL_ROOT, "scripts", "mcal_to_cam19_yaml.py"),
        "--mcal", mcal_file,
        "--output", str(output_yaml)
    ]

    run_command(cmd, "Generate cam19_initial.yaml from .mcal")
    print_success(f"Created: {output_yaml}")


def step4_extract_frames(calibration_session, output_dir, start_time, duration, fps=5):
    """Step 4: Extract frames from all 17 cameras."""
    print_step(4, 8, "Frame Extraction")

    session_synced = Path(output_dir) / f"{calibration_session}_sync" / "cameras_synced"
    output_frames = session_synced / "original"

    # Skip if frames already exist
    existing_frames = list(output_frames.glob("cam*/frame_*.jpg"))
    if len(existing_frames) > 100:
        print_success(f"Frames already extracted ({len(existing_frames)} images)")
        return

    check_dir_exists(output_frames, create=True)

    # Get list of cameras
    cameras = []
    for cam_dir in sorted(session_synced.glob("cam*")):
        if cam_dir.is_dir() and cam_dir.name != "cam19":
            # GoPro cameras
            videos = list(cam_dir.glob("*.MP4")) + list(cam_dir.glob("*.mp4"))
            if videos:
                cameras.append((cam_dir.name, videos[0]))

    # Add cam19 (PrimeColor)
    cam19_video = session_synced / "cam19" / "primecolor_synced.mp4"
    if cam19_video.exists():
        cameras.append(("cam19", cam19_video))

    print(f"  Extracting frames from {len(cameras)} cameras")
    print(f"  Time range: {start_time}s - {start_time + duration}s")
    print(f"  FPS: {fps}")

    # Extract frames for each camera
    for cam_name, video_path in cameras:
        cam_output = output_frames / cam_name
        cam_output.mkdir(parents=True, exist_ok=True)

        # Skip if this camera already has frames
        existing = list(cam_output.glob("frame_*.jpg"))
        if len(existing) > 10:
            print(f"  {cam_name}: Skipping ({len(existing)} frames exist)")
            continue

        print(f"  {cam_name}: Extracting frames...")

        cmd = [
            "python", os.path.join(CSL_ROOT, "scripts", "convert_video_to_images.py"),
            "--video", str(video_path),
            "--output_dir", str(cam_output),
            "--fps", str(fps),
            "--start_sec", str(start_time),
            "--duration", str(duration),
            "--format", "jpg"
        ]

        run_command(cmd, f"Extract frames for {cam_name}", check=False)

    total_frames = len(list(output_frames.glob("cam*/frame_*.jpg")))
    print_success(f"Extracted {total_frames} total frames")


def step5_find_stable_frames(calibration_session, output_dir):
    """Step 5: Detect stable ChArUco frames."""
    print_step(5, 8, "Stable Frame Detection")

    session_synced = Path(output_dir) / f"{calibration_session}_sync" / "cameras_synced"
    input_frames = session_synced / "original"
    output_stable = session_synced / "original_stable"

    # Skip if stable frames already exist
    existing_stable = list(output_stable.glob("cam*/frame_*.jpg"))
    if len(existing_stable) > 50:
        print_success(f"Stable frames already detected ({len(existing_stable)} images)")
        return

    check_dir_exists(input_frames)
    check_dir_exists(output_stable, create=True)

    # Board config
    board_config = os.path.join(CSL_ROOT, "multical", "asset", "charuco_b1_2.yaml")
    check_file_exists(board_config)

    print(f"  Detecting stable frames across all cameras...")

    cmd = [
        "python", os.path.join(CSL_ROOT, "scripts", "find_stable_boards.py"),
        "--input_dir", str(input_frames),
        "--output_dir", str(output_stable),
        "--board", board_config,
        "--movement_threshold", "5.0",
        "--min_detection_quality", "40",
        "--downsample_rate", "10",
        "--max_frames", "500"
    ]

    run_command(cmd, "Stable frame detection")

    total_stable = len(list(output_stable.glob("cam*/frame_*.jpg")))
    print_success(f"Detected {total_stable} stable frames (union across cameras)")


def step6_joint_calibration(calibration_session, output_dir):
    """Step 6: Joint 17-camera extrinsic calibration."""
    print_step(6, 8, "17-Camera Joint Calibration")

    session_synced = Path(output_dir) / f"{calibration_session}_sync" / "cameras_synced"
    stable_frames = session_synced / "original_stable"
    calib_output = stable_frames / "calibration.json"

    # Skip if calibration already exists
    if calib_output.exists():
        print_success("calibration.json already exists")
        # Print RMS error if available
        try:
            with open(calib_output) as f:
                calib_data = json.load(f)
                if "error" in calib_data:
                    rms = calib_data["error"].get("rms", -1)
                    print_success(f"RMS error: {rms:.2f} pixels")
        except:
            pass
        return

    check_dir_exists(stable_frames)

    # Intrinsics file
    intrinsic_file = os.path.join(CSL_ROOT, "intrinsic_all_17_cameras.json")
    check_file_exists(intrinsic_file)

    # Board config
    board_config = os.path.join(CSL_ROOT, "multical", "asset", "charuco_b1_2.yaml")
    check_file_exists(board_config)

    print(f"  Running multical bundle adjustment...")
    print(f"  Input: {stable_frames}")
    print(f"  Intrinsics: {intrinsic_file}")

    # Change to multical directory
    original_cwd = os.getcwd()
    os.chdir(CSL_ROOT)

    try:
        cmd = [
            "python", "-m", "multical.app.calibrate",
            str(stable_frames),
            "--boards", board_config,
            "--intrinsic", intrinsic_file,
            "--fix_intrinsic",
            "--limit_images", "1000"
        ]

        run_command(cmd, "Multical joint calibration")

        # Check output
        if calib_output.exists():
            # Parse RMS error
            with open(calib_output) as f:
                calib_data = json.load(f)
                rms = calib_data.get("error", {}).get("rms", -1)
                if rms > 0:
                    if rms < 1.6:
                        print_success(f"RMS error: {rms:.2f} pixels (excellent)")
                    elif rms < 2.5:
                        print_success(f"RMS error: {rms:.2f} pixels (good)")
                    else:
                        print_warning(f"RMS error: {rms:.2f} pixels (consider refining)")
        else:
            print_error("calibration.json not created")
            sys.exit(1)

    finally:
        os.chdir(original_cwd)


def step7_prompt_cam19_refinement(session, output_dir, mocap_dir):
    """Step 7: Prompt user to refine cam19 interactively."""
    print_step(7, 8, f"Interactive cam19 Refinement for {session}")

    session_synced = Path(output_dir) / f"{session}_sync" / "cameras_synced"
    session_mocap = Path(mocap_dir) / session

    # Check prerequisites
    body_markers = session_mocap / "body_markers.npy"
    marker_names = session_mocap / "body_marker_names.json"
    primecolor_video = session_synced / "cam19" / "primecolor_synced.mp4"
    sync_mapping = session_synced / "cam19" / "sync_mapping.json"
    cam19_initial = session_synced / "cam19_initial.yaml"
    cam19_refined = session_synced / "cam19_refined.yaml"

    # Check if already refined
    if cam19_refined.exists():
        print_success(f"{session}: cam19_refined.yaml already exists")
        return True

    # Check prerequisites
    if not body_markers.exists():
        print_warning(f"{session}: body_markers.npy not found, cannot refine cam19")
        print_warning("  Skipping cam19 refinement for this session")
        return False

    check_file_exists(marker_names)
    check_file_exists(primecolor_video)
    check_file_exists(sync_mapping)
    check_file_exists(cam19_initial)

    # Print instructions
    print(f"\n{Colors.BOLD}{Colors.WARNING}")
    print("="*70)
    print("INTERACTIVE STEP REQUIRED")
    print("="*70)
    print(f"{Colors.ENDC}")

    print(f"\nPlease run the following command to refine cam19 for {session}:\n")

    cmd_str = f"""python post_calibration/refine_extrinsics.py \\
    --markers {body_markers} \\
    --names {marker_names} \\
    --video {primecolor_video} \\
    --camera {cam19_initial} \\
    --output {cam19_refined} \\
    --sync {sync_mapping}"""

    print(f"{Colors.OKCYAN}{cmd_str}{Colors.ENDC}\n")

    print("Controls:")
    print("  a/d: Frame -1/+1    w/W: Frame -2000/+2000")
    print("  f: Find stable      [/]: Time offset -1/+1")
    print("  L-click: Select marker   R-click: Place correction")
    print("  O: Optimize (scipy, 14 params, needs 6+ pairs)")
    print("  e: Export YAML      q: Quit\n")

    print(f"{Colors.BOLD}After refinement, run this script again with --finalize{Colors.ENDC}\n")

    return False


def step8_generate_individual_yamls(session, output_dir, calibration_session):
    """Step 8: Generate individual camera YAMLs."""
    print_step(8, 8, f"Generate Individual Camera YAMLs for {session}")

    session_synced = Path(output_dir) / f"{session}_sync" / "cameras_synced"
    calib_session_synced = Path(output_dir) / f"{calibration_session}_sync" / "cameras_synced"

    # Check inputs
    calib_json = calib_session_synced / "original_stable" / "calibration.json"
    cam19_refined = session_synced / "cam19_refined.yaml"
    output_yaml_dir = session_synced / "individual_cam_params"

    # Skip if YAMLs already exist
    existing_yamls = list(output_yaml_dir.glob("cam*.yaml"))
    if len(existing_yamls) >= 17:
        print_success(f"{session}: Individual YAMLs already exist ({len(existing_yamls)} files)")
        return

    check_file_exists(calib_json)
    check_file_exists(cam19_refined)
    check_dir_exists(output_yaml_dir, create=True)

    print(f"  Generating YAMLs for {session}...")
    print(f"  Calibration: {calib_json}")
    print(f"  cam19: {cam19_refined}")

    cmd = [
        "python", os.path.join(CSL_ROOT, "post_calibration", "generate_individual_cam_yaml.py"),
        "--calib_json", str(calib_json),
        "--cam19_yaml", str(cam19_refined),
        "--output_dir", str(output_yaml_dir)
    ]

    run_command(cmd, "Generate individual YAMLs")

    # Count output files
    yaml_files = list(output_yaml_dir.glob("cam*.yaml"))
    print_success(f"Generated {len(yaml_files)} camera YAML files")


def step9_create_gt_symlinks(session, output_dir, mocap_dir):
    """Step 9: Create symlinks to GT source data in cam19."""
    print_step(9, 8, f"Create GT Symlinks for {session}")

    session_synced = Path(output_dir) / f"{session}_sync" / "cameras_synced"
    session_mocap = Path(mocap_dir) / session
    cam19_dir = session_synced / "cam19"

    check_dir_exists(cam19_dir)

    # Symlink skeleton_h36m.npy
    src_skeleton = session_mocap / "skeleton_h36m.npy"
    dst_skeleton = cam19_dir / "skeleton_h36m.npy"

    if src_skeleton.exists():
        if not dst_skeleton.exists():
            os.symlink(src_skeleton, dst_skeleton)
            print_success(f"Created: skeleton_h36m.npy symlink")
        else:
            print_success("skeleton_h36m.npy symlink exists")
    else:
        print_warning(f"Source skeleton not found: {src_skeleton}")

    # Symlink blade_edges.npy → aligned_edges.npy
    src_blade = session_mocap / "blade_edges.npy"
    dst_blade = cam19_dir / "aligned_edges.npy"

    if src_blade.exists():
        if not dst_blade.exists():
            os.symlink(src_blade, dst_blade)
            print_success(f"Created: aligned_edges.npy symlink")
        else:
            print_success("aligned_edges.npy symlink exists")
    else:
        print_warning(f"Source blade_edges not found: {src_blade}")


def step10_distribute_gt(session, output_dir):
    """Step 10: Distribute GT data to per-camera folders."""
    print_step(10, 8, f"Distribute GT for {session}")

    session_synced = Path(output_dir) / f"{session}_sync" / "cameras_synced"

    # Check if GT already distributed
    existing_gt = list(session_synced.glob("cam*/gt/skeleton.npy"))
    if len(existing_gt) >= 16:
        print_success(f"{session}: GT already distributed ({len(existing_gt)} cameras)")
        return

    print(f"  Distributing GT for {session}...")

    cmd = [
        "python", os.path.join(CSL_ROOT, "scripts", "distribute_gt.py"),
        "--session_dir", str(session_synced),
        "--force"
    ]

    run_command(cmd, "GT distribution")

    # Count distributed GT
    gt_files = list(session_synced.glob("cam*/gt/skeleton.npy"))
    print_success(f"Distributed GT to {len(gt_files)} cameras")


def main():
    parser = argparse.ArgumentParser(
        description='Complete GoPro calibration pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('Usage:')[1])

    # Input/Output paths
    parser.add_argument('--organized_dir', required=True,
                        help='GoPro organized directory (per-session structure)')
    parser.add_argument('--mocap_dir', required=True,
                        help='Mocap data directory (output from process_mocap_session.py)')
    parser.add_argument('--output_dir', required=True,
                        help='Output directory for synced data')

    # Calibration settings
    parser.add_argument('--calibration_session', required=True,
                        help='Session to use for calibration (e.g., P7_2)')
    parser.add_argument('--sessions', nargs='+', required=True,
                        help='List of sessions to process (e.g., P7_1 P7_2 P7_3)')

    # Optional inputs
    parser.add_argument('--anchor_video',
                        help='QR anchor video for GoPro sync')
    parser.add_argument('--mcal_file',
                        help='OptiTrack .mcal file for cam19_initial.yaml')

    # Calibration parameters (only for calibration session)
    parser.add_argument('--start_time', type=float, default=334,
                        help='Frame extraction start time (seconds)')
    parser.add_argument('--duration', type=float, default=292,
                        help='Frame extraction duration (seconds)')
    parser.add_argument('--fps', type=float, default=5,
                        help='Frame extraction FPS')

    # Pipeline control
    parser.add_argument('--skip_sync', action='store_true',
                        help='Skip GoPro and PrimeColor synchronization')
    parser.add_argument('--skip_calibration', action='store_true',
                        help='Skip calibration (use for non-calibration sessions)')
    parser.add_argument('--finalize', action='store_true',
                        help='Finalize mode: generate YAMLs + distribute GT (after cam19 refinement)')

    args = parser.parse_args()

    # Validate inputs
    organized_dir = Path(args.organized_dir)
    mocap_dir = Path(args.mocap_dir)
    output_dir = Path(args.output_dir)

    if not organized_dir.exists():
        print_error(f"Organized directory not found: {organized_dir}")
        sys.exit(1)

    if not mocap_dir.exists():
        print_error(f"Mocap directory not found: {mocap_dir}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine mode
    is_calibration_mode = args.calibration_session in args.sessions and not args.skip_calibration
    is_finalize_mode = args.finalize

    # Print pipeline info
    print_header("GoPro Calibration Pipeline")

    print(f"Organized dir:  {organized_dir}")
    print(f"Mocap dir:      {mocap_dir}")
    print(f"Output dir:     {output_dir}")
    print(f"Calibration session: {args.calibration_session}")
    print(f"Sessions:       {', '.join(args.sessions)}")

    if is_calibration_mode:
        print(f"\n{Colors.BOLD}Mode: CALIBRATION (full pipeline){Colors.ENDC}")
        print(f"  Start time: {args.start_time}s")
        print(f"  Duration:   {args.duration}s")
        print(f"  FPS:        {args.fps}")
    elif is_finalize_mode:
        print(f"\n{Colors.BOLD}Mode: FINALIZE (post-refinement){Colors.ENDC}")
    else:
        print(f"\n{Colors.BOLD}Mode: REGULAR (using shared calibration){Colors.ENDC}")

    # Pipeline execution
    try:
        # Steps 1-2: Synchronization (unless skipped)
        if not args.skip_sync and not is_finalize_mode:
            if not args.anchor_video:
                print_error("--anchor_video required for synchronization")
                sys.exit(1)

            step1_gopro_sync(organized_dir, output_dir, args.anchor_video, args.sessions)
            step2_primecolor_sync(mocap_dir, output_dir, args.sessions)
        else:
            print_warning("Skipping synchronization (--skip_sync or --finalize)")

        # Steps 3-6: Calibration (only for calibration session)
        if is_calibration_mode and not is_finalize_mode:
            if not args.mcal_file:
                print_error("--mcal_file required for calibration mode")
                sys.exit(1)

            step3_create_cam19_initial(args.mcal_file, args.calibration_session, output_dir)
            step4_extract_frames(args.calibration_session, output_dir, args.start_time, args.duration, args.fps)
            step5_find_stable_frames(args.calibration_session, output_dir)
            step6_joint_calibration(args.calibration_session, output_dir)

            # Step 7: Prompt for interactive refinement
            all_refined = True
            for session in args.sessions:
                if not step7_prompt_cam19_refinement(session, output_dir, mocap_dir):
                    all_refined = False

            if not all_refined:
                print(f"\n{Colors.BOLD}{Colors.WARNING}")
                print("="*70)
                print("PIPELINE PAUSED")
                print("="*70)
                print(f"{Colors.ENDC}")
                print("\nPlease complete the cam19 refinement steps above,")
                print("then run this script again with --finalize to complete the pipeline.\n")
                sys.exit(0)

        # Steps 8-10: Finalization (generate YAMLs + distribute GT)
        if is_finalize_mode or (is_calibration_mode and not args.skip_calibration):
            for session in args.sessions:
                # Check if cam19_refined exists
                session_synced = Path(output_dir) / f"{session}_sync" / "cameras_synced"
                cam19_refined = session_synced / "cam19_refined.yaml"

                if not cam19_refined.exists():
                    print_warning(f"{session}: cam19_refined.yaml not found, skipping YAML generation")
                    continue

                step8_generate_individual_yamls(session, output_dir, args.calibration_session)
                step9_create_gt_symlinks(session, output_dir, mocap_dir)
                step10_distribute_gt(session, output_dir)

        # Success summary
        print_header("Pipeline Complete!")

        print(f"Processed sessions: {', '.join(args.sessions)}")

        if is_calibration_mode and not is_finalize_mode:
            print(f"\nCalibration session: {args.calibration_session}")
            calib_json = Path(output_dir) / f"{args.calibration_session}_sync" / "cameras_synced" / "original_stable" / "calibration.json"
            if calib_json.exists():
                print_success(f"Shared calibration: {calib_json}")

        print(f"\nOutput directory: {output_dir}")
        print("\nNext steps:")
        if not is_finalize_mode:
            print("  1. Review calibration quality")
            print("  2. Optionally verify GT temporal alignment:")
            print(f"     python post_calibration/verify_gt_offset.py --session_dir <session>/cameras_synced --camera cam1")
        else:
            print("  Pipeline complete! All sessions processed.")

    except KeyboardInterrupt:
        print(f"\n\n{Colors.WARNING}Pipeline interrupted by user{Colors.ENDC}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
