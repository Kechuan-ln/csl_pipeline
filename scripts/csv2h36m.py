#!/usr/bin/env python3
"""
Universal CSV to H36M converter for P4-P6 datasets.

Automatically handles different skeleton prefixes and marker naming conventions:
- Skeleton prefixes: body, Skeleton 001, P2, P3
- Knee/ankle markers: L1-L4, R1-R4 in various markersets
- Two amputation modes: right leg (P4, P5_3, P6) or left leg (P5_2, P5_4, P5_5)

H36M Joint Order (17 joints):
    0: Hip (Pelvis)
    1: RHip
    2: RKnee
    3: RAnkle
    4: LHip
    5: LKnee
    6: LAnkle
    7: Spine
    8: Thorax
    9: Nose
    10: Head
    11: LShoulder
    12: LElbow
    13: LWrist
    14: RShoulder
    15: RElbow
    16: RWrist

Coordinate System (Motive):
    - Y-up
    - Z-forward
    - X-left/right
    - Units: millimeters

Usage:
    python csv2h36m.py input.csv -o skeleton_h36m.npy
    python csv2h36m.py input.csv --postprocess --preview 10
"""

import numpy as np
import pandas as pd
import argparse
from pathlib import Path
import json

from motive_csv_utils import load_motive_csv, detect_skeleton_prefix


H36M_JOINT_NAMES = [
    'Hip', 'RHip', 'RKnee', 'RAnkle',
    'LHip', 'LKnee', 'LAnkle',
    'Spine', 'Thorax', 'Nose', 'Head',
    'LShoulder', 'LElbow', 'LWrist',
    'RShoulder', 'RElbow', 'RWrist'
]


def detect_amputation_mode(df):
    """
    Detect amputation mode based on available markers.

    Returns:
        'right_leg': Right leg amputated (has L1-L2 for left knee, R1-R4 for right)
        'left_leg': Left leg amputated (has L1-L4 for left, R1-R2 for right)
        'unknown': Cannot determine (e.g., P5_1 with no L/R naming)
    """
    # Find marker columns
    has_l3 = any(':L3_Marker_Position_X' in col or ':L3_Rigid Body Marker_Position_X' in col for col in df.columns)
    has_l4 = any(':L4_Marker_Position_X' in col or ':L4_Rigid Body Marker_Position_X' in col for col in df.columns)
    has_r3 = any(':R3_Marker_Position_X' in col or ':R3_Rigid Body Marker_Position_X' in col for col in df.columns)
    has_r4 = any(':R4_Marker_Position_X' in col or ':R4_Rigid Body Marker_Position_X' in col for col in df.columns)
    has_l1 = any(':L1_Marker_Position_X' in col or ':L1_Rigid Body Marker_Position_X' in col for col in df.columns)
    has_r1 = any(':R1_Marker_Position_X' in col or ':R1_Rigid Body Marker_Position_X' in col for col in df.columns)

    # Check for L/R naming at all
    if not has_l1 and not has_r1:
        return 'unknown'

    # Left leg amputated: has L3/L4 for left ankle, no R3/R4
    if (has_l3 or has_l4) and not (has_r3 or has_r4):
        return 'left_leg'

    # Right leg amputated: has R3/R4 for right ankle, no L3/L4
    if (has_r3 or has_r4) and not (has_l3 or has_l4):
        return 'right_leg'

    # Bilateral: has L1/R1 (knee markers) but no ankle markers on either side
    if (has_l1 and has_r1) and not (has_l3 or has_l4 or has_r3 or has_r4):
        return 'bilateral'

    return 'unknown'


def find_marker_columns(df, marker_suffix, marker_type='Marker'):
    """
    Find marker columns by suffix pattern.

    Searches for patterns like:
        - Markerset:L1_Marker_Position_X
        - RigidBody:R1_Rigid Body Marker_Position_X

    Returns:
        (marker_name, [x_col, y_col, z_col]) or (None, None)
    """
    pattern_x = f':{marker_suffix}_{marker_type}_Position_X'

    candidates = []
    for col in df.columns:
        if pattern_x in col:
            base = col.replace(f'_{marker_type}_Position_X', '')
            x_col = col
            y_col = f'{base}_{marker_type}_Position_Y'
            z_col = f'{base}_{marker_type}_Position_Z'

            if y_col in df.columns and z_col in df.columns:
                valid_count = df[x_col].notna().sum()
                candidates.append((valid_count, base, [x_col, y_col, z_col]))

    if not candidates:
        return None, None

    # Pick candidate with most valid data
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], candidates[0][2]


def preprocess_markers(df, skeleton_prefix, search_range=1000):
    """
    Fill missing markers using nearest-frame offset method.

    When a marker is missing but its reference marker is valid, estimate
    the missing marker using the offset from the nearest frame where both
    are valid.
    """
    n_frames = len(df)

    # Static pairs for pelvis and head markers
    static_pairs = [
        # Pelvis markers
        (f'{skeleton_prefix}:LASI_Marker_Position', f'{skeleton_prefix}:LPSI_Marker_Position'),
        (f'{skeleton_prefix}:RASI_Marker_Position', f'{skeleton_prefix}:RPSI_Marker_Position'),
        (f'{skeleton_prefix}:LPSI_Marker_Position', f'{skeleton_prefix}:LASI_Marker_Position'),
        (f'{skeleton_prefix}:RPSI_Marker_Position', f'{skeleton_prefix}:RASI_Marker_Position'),
        (f'{skeleton_prefix}:LASI_Marker_Position', f'{skeleton_prefix}:RASI_Marker_Position'),
        (f'{skeleton_prefix}:RASI_Marker_Position', f'{skeleton_prefix}:LASI_Marker_Position'),
        (f'{skeleton_prefix}:LPSI_Marker_Position', f'{skeleton_prefix}:RPSI_Marker_Position'),
        (f'{skeleton_prefix}:RPSI_Marker_Position', f'{skeleton_prefix}:LPSI_Marker_Position'),
        # Head markers
        (f'{skeleton_prefix}:LFHD_Marker_Position', f'{skeleton_prefix}:RFHD_Marker_Position'),
        (f'{skeleton_prefix}:RFHD_Marker_Position', f'{skeleton_prefix}:LFHD_Marker_Position'),
        (f'{skeleton_prefix}:LBHD_Marker_Position', f'{skeleton_prefix}:RBHD_Marker_Position'),
        (f'{skeleton_prefix}:RBHD_Marker_Position', f'{skeleton_prefix}:LBHD_Marker_Position'),
    ]

    # Dynamic pairs for knee/ankle markers
    dynamic_suffix_pairs = [
        ('L1', 'L2'), ('L2', 'L1'),
        ('L3', 'L4'), ('L4', 'L3'),
        ('R1', 'R2'), ('R2', 'R1'),
        ('R3', 'R4'), ('R4', 'R3'),
    ]

    marker_pairs = []

    # Add static pairs
    for missing_prefix, ref_prefix in static_pairs:
        missing_cols = [f'{missing_prefix}_{axis}' for axis in ['X', 'Y', 'Z']]
        ref_cols = [f'{ref_prefix}_{axis}' for axis in ['X', 'Y', 'Z']]
        if all(col in df.columns for col in missing_cols + ref_cols):
            label = missing_prefix.split(':')[1].split('_')[0]
            marker_pairs.append((missing_cols, ref_cols, label))

    # Add dynamic pairs
    for missing_suffix, ref_suffix in dynamic_suffix_pairs:
        missing_name, missing_cols = find_marker_columns(df, missing_suffix)
        ref_name, ref_cols = find_marker_columns(df, ref_suffix)
        if missing_cols and ref_cols:
            marker_pairs.append((missing_cols, ref_cols, missing_suffix))

    total_filled = 0

    for missing_cols, ref_cols, marker_label in marker_pairs:
        missing_nan = df[missing_cols[0]].isna()
        ref_valid = ~df[ref_cols[0]].isna()
        frames_to_fill = np.where(missing_nan & ref_valid)[0]

        if len(frames_to_fill) == 0:
            continue

        both_valid = (~df[missing_cols[0]].isna()) & (~df[ref_cols[0]].isna())
        valid_indices = np.where(both_valid)[0]

        if len(valid_indices) == 0:
            continue

        filled_count = 0
        for frame in frames_to_fill:
            distances = np.abs(valid_indices - frame)
            within_range = distances <= search_range
            if not np.any(within_range):
                continue

            nearest_idx = valid_indices[within_range][np.argmin(distances[within_range])]

            offset = np.array([
                df.loc[nearest_idx, missing_cols[0]] - df.loc[nearest_idx, ref_cols[0]],
                df.loc[nearest_idx, missing_cols[1]] - df.loc[nearest_idx, ref_cols[1]],
                df.loc[nearest_idx, missing_cols[2]] - df.loc[nearest_idx, ref_cols[2]],
            ])

            for i in range(3):
                df.loc[frame, missing_cols[i]] = df.loc[frame, ref_cols[i]] + offset[i]

            filled_count += 1

        if filled_count > 0:
            print(f"  Filled {filled_count} frames for {marker_label}")
            total_filled += filled_count

    return df, total_filled


def preprocess_markers_multi_pass(df, skeleton_prefix, search_range=1000, max_passes=5):
    """Multi-pass marker preprocessing."""
    print("Preprocessing markers (multi-pass)...")

    total_filled_all = 0
    for pass_num in range(max_passes):
        df, filled = preprocess_markers(df, skeleton_prefix, search_range)
        total_filled_all += filled
        if filled == 0:
            print(f"  Pass {pass_num + 1}: no more markers to fill")
            break
        print(f"  Pass {pass_num + 1}: filled {filled} markers")

    # Interpolation for critical markers
    critical_prefixes = [
        f'{skeleton_prefix}:LASI_Marker_Position',
        f'{skeleton_prefix}:RASI_Marker_Position',
        f'{skeleton_prefix}:LPSI_Marker_Position',
        f'{skeleton_prefix}:RPSI_Marker_Position',
        f'{skeleton_prefix}:LFHD_Marker_Position',
        f'{skeleton_prefix}:RFHD_Marker_Position',
        f'{skeleton_prefix}:LBHD_Marker_Position',
        f'{skeleton_prefix}:RBHD_Marker_Position',
    ]

    interp_count = 0
    for marker_prefix in critical_prefixes:
        for axis in ['X', 'Y', 'Z']:
            col = f'{marker_prefix}_{axis}'
            if col not in df.columns:
                continue

            series = df[col]
            nan_count = series.isna().sum()
            if nan_count == 0 or nan_count == len(series):
                continue

            df[col] = series.interpolate(method='linear', limit_area='inside')
            df[col] = df[col].ffill().bfill()

            new_nan_count = df[col].isna().sum()
            interp_count += nan_count - new_nan_count

    if interp_count > 0:
        print(f"  Final interpolation: filled {interp_count} values")

    print(f"  Total preprocessing: {total_filled_all + interp_count} values filled")
    return df


def extract_h36m_vectorized(df, skeleton_prefix, amputation_mode, nose_length=100.0):
    """
    Vectorized extraction of H36M 17-joint skeleton from DataFrame.

    Args:
        df: DataFrame from load_motive_csv()
        skeleton_prefix: 'body', 'Skeleton 001', 'P2', or 'P3'
        amputation_mode: 'right_leg' or 'left_leg'
        nose_length: Distance from head center to nose (mm)

    Returns:
        np.array of shape (N_frames, 17, 3)
    """
    n_frames = len(df)
    joints = np.full((n_frames, 17, 3), np.nan)

    def get_col(col_name):
        if col_name in df.columns:
            return df[col_name].values.astype(np.float64)
        return np.full(n_frames, np.nan)

    def get_marker(name, marker_type='Marker'):
        x = get_col(f'{name}_{marker_type}_Position_X')
        y = get_col(f'{name}_{marker_type}_Position_Y')
        z = get_col(f'{name}_{marker_type}_Position_Z')
        return np.stack([x, y, z], axis=1)

    def get_bone(name):
        x = get_col(f'{skeleton_prefix}:{name}_Bone_Position_X')
        y = get_col(f'{skeleton_prefix}:{name}_Bone_Position_Y')
        z = get_col(f'{skeleton_prefix}:{name}_Bone_Position_Z')
        return np.stack([x, y, z], axis=1)

    def get_quat(name):
        qx = get_col(f'{skeleton_prefix}:{name}_Bone_Rotation_X')
        qy = get_col(f'{skeleton_prefix}:{name}_Bone_Rotation_Y')
        qz = get_col(f'{skeleton_prefix}:{name}_Bone_Rotation_Z')
        qw = get_col(f'{skeleton_prefix}:{name}_Bone_Rotation_W')
        return np.stack([qx, qy, qz, qw], axis=1)

    def find_marker_array(suffix, marker_type='Marker'):
        """Find marker by suffix and return (N, 3) array."""
        pattern = f':{suffix}_{marker_type}_Position_X'
        candidates = []
        for col in df.columns:
            if pattern in col:
                base = col.replace(f'_{marker_type}_Position_X', '')
                y_col = f'{base}_{marker_type}_Position_Y'
                z_col = f'{base}_{marker_type}_Position_Z'
                if y_col in df.columns and z_col in df.columns:
                    valid_count = df[col].notna().sum()
                    candidates.append((valid_count, base))
        if not candidates:
            return np.full((n_frames, 3), np.nan)
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_base = candidates[0][1]
        if len(candidates) > 1:
            print(f"    {suffix}: {len(candidates)} matches, picked {best_base} ({candidates[0][0]} valid frames)")
        return get_marker(best_base, marker_type)

    print(f"  Extracting joints using {skeleton_prefix} (mode: {amputation_mode})...")

    # --- Pelvis markers ---
    lasi = get_marker(f'{skeleton_prefix}:LASI')
    rasi = get_marker(f'{skeleton_prefix}:RASI')
    lpsi = get_marker(f'{skeleton_prefix}:LPSI')
    rpsi = get_marker(f'{skeleton_prefix}:RPSI')

    # Joint 0: Hip (pelvis center)
    joints[:, 0, :] = (lasi + rasi + lpsi + rpsi) / 4.0

    # Joint 1: RHip = (RASI + RPSI) / 2
    joints[:, 1, :] = (rasi + rpsi) / 2.0

    # Joint 4: LHip = (LASI + LPSI) / 2
    joints[:, 4, :] = (lasi + lpsi) / 2.0

    # --- Knee markers (always L1+L2 for left, R1+R2 for right) ---
    l1 = find_marker_array('L1')
    l2 = find_marker_array('L2')
    r1 = find_marker_array('R1')
    r2 = find_marker_array('R2')

    # Joint 5: LKnee = (L1 + L2) / 2
    joints[:, 5, :] = (l1 + l2) / 2.0

    # Joint 2: RKnee = (R1 + R2) / 2
    joints[:, 2, :] = (r1 + r2) / 2.0

    # --- Ankle markers (depends on amputation mode) ---
    if amputation_mode == 'right_leg':
        # Right leg amputated: R3+R4 for right ankle, left ankle = NaN
        r3 = find_marker_array('R3')
        r4 = find_marker_array('R4')
        joints[:, 3, :] = (r3 + r4) / 2.0  # RAnkle
        joints[:, 6, :] = np.nan  # LAnkle (amputated)
        print(f"    Right leg mode: RAnkle from R3+R4, LAnkle=NaN")
    elif amputation_mode == 'left_leg':
        # Left leg amputated: L3+L4 for left ankle, right ankle = NaN
        l3 = find_marker_array('L3')
        l4 = find_marker_array('L4')
        joints[:, 6, :] = (l3 + l4) / 2.0  # LAnkle
        joints[:, 3, :] = np.nan  # RAnkle (amputated)
        print(f"    Left leg mode: LAnkle from L3+L4, RAnkle=NaN")
    elif amputation_mode == 'bilateral':
        # Bilateral: both legs amputated, no ankle markers
        joints[:, 3, :] = np.nan
        joints[:, 6, :] = np.nan
        print(f"    Bilateral mode: both ankles=NaN")
    else:
        # Unknown: both ankles = NaN
        joints[:, 3, :] = np.nan
        joints[:, 6, :] = np.nan
        print(f"    Unknown mode: both ankles=NaN")

    # --- Spine chain ---
    joints[:, 7, :] = get_bone('Chest')
    joints[:, 8, :] = get_bone('Neck')

    # --- Head ---
    lfhd = get_marker(f'{skeleton_prefix}:LFHD')
    rfhd = get_marker(f'{skeleton_prefix}:RFHD')
    lbhd = get_marker(f'{skeleton_prefix}:LBHD')
    rbhd = get_marker(f'{skeleton_prefix}:RBHD')
    joints[:, 10, :] = (lfhd + rfhd + lbhd + rbhd) / 4.0

    # Joint 9: Nose (from Head bone + rotation)
    head_pos = get_bone('Head')
    head_quat = get_quat('Head')

    qx, qy, qz, qw = head_quat[:, 0], head_quat[:, 1], head_quat[:, 2], head_quat[:, 3]
    forward_x = 2.0 * (qw * qy + qz * qx)
    forward_y = 2.0 * (qz * qy - qw * qx)
    forward_z = 1.0 - 2.0 * (qx * qx + qy * qy)

    forward_len = np.sqrt(forward_x**2 + forward_y**2 + forward_z**2)
    forward_len = np.where(forward_len > 1e-6, forward_len, 1.0)
    forward_x /= forward_len
    forward_y /= forward_len
    forward_z /= forward_len

    joints[:, 9, 0] = head_pos[:, 0] + forward_x * nose_length
    joints[:, 9, 1] = head_pos[:, 1] + forward_y * nose_length
    joints[:, 9, 2] = head_pos[:, 2] + forward_z * nose_length

    # --- Arms ---
    joints[:, 11, :] = get_bone('LUArm')
    joints[:, 12, :] = get_bone('LFArm')
    joints[:, 13, :] = get_bone('LHand')
    joints[:, 14, :] = get_bone('RUArm')
    joints[:, 15, :] = get_bone('RFArm')
    joints[:, 16, :] = get_bone('RHand')

    print("  Extraction complete")
    return joints


def interpolate_missing(joints):
    """Interpolate missing (NaN) values using linear interpolation."""
    from scipy import interpolate

    joints = joints.copy()
    n_frames = len(joints)
    total_interpolated = 0

    for j in range(17):
        for axis in range(3):
            data = joints[:, j, axis]
            nan_mask = np.isnan(data)

            if nan_mask.sum() == 0 or nan_mask.sum() == n_frames:
                continue

            valid_idx = np.where(~nan_mask)[0]
            nan_idx = np.where(nan_mask)[0]

            interp_idx = nan_idx[(nan_idx > valid_idx.min()) & (nan_idx < valid_idx.max())]

            if len(interp_idx) > 0:
                f = interpolate.interp1d(valid_idx, data[valid_idx], kind='linear')
                joints[interp_idx, j, axis] = f(interp_idx)
                total_interpolated += len(interp_idx)

    return joints, total_interpolated // 3


def postprocess_joints(joints, interactive=False):
    """Post-process joints: interpolate missing values."""
    print("\n=== Post-processing ===")

    n_frames = len(joints)

    print(f"\n1. Missing values before interpolation:")
    for j, name in enumerate(H36M_JOINT_NAMES):
        nan_count = np.isnan(joints[:, j, 0]).sum()
        if nan_count > 0:
            print(f"   {name:12s}: {nan_count} frames ({100*nan_count/n_frames:.1f}%)")

    joints, interp_count = interpolate_missing(joints)
    print(f"\n   Interpolated {interp_count} missing frames")

    print(f"\n2. Final missing values:")
    total_nan = 0
    for j, name in enumerate(H36M_JOINT_NAMES):
        nan_count = np.isnan(joints[:, j, 0]).sum()
        if nan_count > 0:
            print(f"   {name:12s}: {nan_count} frames")
            total_nan += nan_count

    if total_nan == 0:
        print("   None (all joints complete)")

    return joints


def apply_marker_map(df, marker_map):
    """
    Rename marker columns using a mapping dict.

    marker_map: dict like {'P2Lg:Marker 004': 'P2Lg:L1', ...}
    """
    rename_dict = {}
    for old_prefix, new_prefix in marker_map.items():
        for marker_type in ['Marker', 'Rigid Body Marker']:
            for prop in ['Position']:
                for axis in ['X', 'Y', 'Z']:
                    old_col = f'{old_prefix}_{marker_type}_{prop}_{axis}'
                    new_col = f'{new_prefix}_{marker_type}_{prop}_{axis}'
                    if old_col in df.columns:
                        rename_dict[old_col] = new_col

    if rename_dict:
        print(f"  Marker map: renaming {len(rename_dict)} columns")
        for old, new in sorted(rename_dict.items()):
            if '_X' in old:
                print(f"    {old.split('_Marker_')[0]} -> {new.split('_Marker_')[0]}")
        df = df.rename(columns=rename_dict)
    return df


def convert_csv_to_h36m(csv_file, nose_length=100.0, preprocess=True, search_range=1000,
                        marker_map=None, force_amputation=None):
    """
    Convert Motive CSV to H36M format.

    Automatically detects skeleton prefix and amputation mode.
    """
    print(f"Loading CSV: {csv_file}")
    df = load_motive_csv(csv_file)

    n_frames = len(df)
    print(f"Total frames: {n_frames}")

    # Apply marker name mapping if provided
    if marker_map:
        df = apply_marker_map(df, marker_map)

    # Auto-detect skeleton prefix
    skeleton_prefix = detect_skeleton_prefix(df)
    if skeleton_prefix:
        print(f"Detected skeleton prefix: {skeleton_prefix}")
    else:
        print("Warning: Could not detect skeleton prefix")
        return None

    # Auto-detect amputation mode
    if force_amputation:
        amputation_mode = force_amputation
        print(f"Forced amputation mode: {amputation_mode}")
    else:
        amputation_mode = detect_amputation_mode(df)
        if amputation_mode == 'unknown':
            print("Warning: Could not detect amputation mode (no L/R marker naming)")
            print("  Use --marker-map and --amputation to specify manually")
            return None
        print(f"Detected amputation mode: {amputation_mode}")
        if amputation_mode == 'bilateral':
            print("  (Bilateral: both legs amputated, both ankles will be NaN)")

    # Preprocess markers
    if preprocess:
        df = preprocess_markers_multi_pass(df, skeleton_prefix, search_range)

    # Extract joints
    joints = extract_h36m_vectorized(df, skeleton_prefix, amputation_mode, nose_length)

    return joints


def main():
    parser = argparse.ArgumentParser(description='Universal CSV to H36M converter for P4-P6 datasets')
    parser.add_argument('csv_file', help='Input CSV file')
    parser.add_argument('-o', '--output', help='Output NPY file (default: input_h36m.npy)')
    parser.add_argument('--nose-length', type=float, default=100.0,
                        help='Nose offset from head center in mm (default: 100)')
    parser.add_argument('--meters', action='store_true',
                        help='Convert output to meters (default: millimeters)')
    parser.add_argument('--preview', type=int, default=0,
                        help='Preview first N frames (0 = no preview)')
    parser.add_argument('--postprocess', action='store_true',
                        help='Run post-processing (interpolation)')
    parser.add_argument('--no-preprocess', action='store_true',
                        help='Skip marker preprocessing')
    parser.add_argument('--search-range', type=int, default=100,
                        help='Max frames to search for reference markers (default: 100)')
    parser.add_argument('--marker-map', type=str, default=None,
                        help='Marker name mapping as comma-separated old=new pairs, '
                             'e.g. "P2Lg:Marker 004=P2Lg:L1,P2Lg:Marker 003=P2Lg:L2"')
    parser.add_argument('--amputation', type=str, default=None,
                        choices=['left_leg', 'right_leg'],
                        help='Force amputation mode instead of auto-detect')

    args = parser.parse_args()

    # Parse marker map
    marker_map = None
    if args.marker_map:
        marker_map = {}
        for pair in args.marker_map.split(','):
            old, new = pair.strip().split('=')
            marker_map[old.strip()] = new.strip()

    # Convert
    joints = convert_csv_to_h36m(
        args.csv_file,
        args.nose_length,
        preprocess=not args.no_preprocess,
        search_range=args.search_range,
        marker_map=marker_map,
        force_amputation=args.amputation,
    )

    if joints is None:
        print("Conversion failed")
        return 1

    # Post-processing
    if args.postprocess:
        joints = postprocess_joints(joints, interactive=False)

    # Unit conversion
    if args.meters:
        joints = joints / 1000.0
        print("Converted to meters")

    # Output file
    if args.output:
        output_file = args.output
    else:
        output_file = Path(args.csv_file).stem + '_h36m.npy'

    # Save
    np.save(output_file, joints)
    print(f"\nSaved to: {output_file}")
    print(f"Shape: {joints.shape}")

    # Preview
    if args.preview > 0:
        print(f"\n=== Preview Frame 0 ===")
        for i, name in enumerate(H36M_JOINT_NAMES):
            pos = joints[0, i]
            if np.any(np.isnan(pos)):
                print(f"  {i:2d} {name:12s}: NaN")
            else:
                unit = 'm' if args.meters else 'mm'
                print(f"  {i:2d} {name:12s}: ({pos[0]:8.1f}, {pos[1]:8.1f}, {pos[2]:8.1f}) {unit}")

    # Statistics
    valid_mask = ~np.isnan(joints).any(axis=2)
    valid_per_joint = valid_mask.sum(axis=0)
    print(f"\n=== Valid frames per joint ===")
    for i, name in enumerate(H36M_JOINT_NAMES):
        pct = 100.0 * valid_per_joint[i] / len(joints)
        print(f"  {i:2d} {name:12s}: {valid_per_joint[i]:6d} / {len(joints)} ({pct:5.1f}%)")

    return 0


if __name__ == '__main__':
    exit(main())
