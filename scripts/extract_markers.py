#!/usr/bin/env python3
"""
Extract body markers and leg markers from OptiTrack Motive CSV.

Automatically handles different skeleton prefixes:
    - body (P4_1-P4_4)
    - Skeleton 001 (P4_5)
    - P2 (P5_1, P5_2, P5_4, P5_5)
    - P3 (P5_3, P6_1-P6_5)

Outputs:
    - body_markers.npy: (N_frames, 27, 3) array of body markers
    - body_marker_names.json: list of 27 marker names
    - leg_markers.npy: (N_frames, M, 3) array of leg markers (optional)
    - leg_marker_names.json: list of leg marker names (optional)

Usage:
    python extract_markers.py /Volumes/T7/csl/P4_1/Take*.csv
    python extract_markers.py input.csv -o /Volumes/T7/csl/P4_1/
    python extract_markers.py input.csv --legs  # also extract leg markers
"""

import numpy as np
import argparse
import json
from pathlib import Path

from motive_csv_utils import load_motive_csv, detect_skeleton_prefix


# Standard body markers (same across all datasets)
BODY_MARKER_NAMES = [
    'C7', 'CLAV', 'LASI', 'LBHD', 'LELB', 'LFHD', 'LFIN', 'LFRM',
    'LPSI', 'LSHO', 'LUPA', 'LWRA', 'LWRB',
    'RASI', 'RBAK', 'RBHD', 'RELB', 'RFHD', 'RFIN', 'RFRM',
    'RPSI', 'RSHO', 'RUPA', 'RWRA', 'RWRB',
    'STRN', 'T10'
]

# Leg marker suffixes to search for
LEG_MARKER_SUFFIXES = ['L1', 'L2', 'L3', 'L4', 'R1', 'R2', 'R3', 'R4']


def find_marker_columns_by_suffix(df, suffix, marker_type='Marker'):
    """Find marker columns by suffix (e.g., 'L1' matches any ':L1' marker)."""
    pattern_x = f':{suffix}_{marker_type}_Position_X'

    for col in df.columns:
        if pattern_x in col:
            base = col.replace(f'_{marker_type}_Position_X', '')
            x_col = col
            y_col = f'{base}_{marker_type}_Position_Y'
            z_col = f'{base}_{marker_type}_Position_Z'

            if y_col in df.columns and z_col in df.columns:
                return base, [x_col, y_col, z_col]

    return None, None


def extract_body_markers(df, skeleton_prefix):
    """
    Extract all 27 body markers as (N, 27, 3) array.

    Body markers are skeleton bone markers with names like:
        {skeleton_prefix}:{marker_name}_Marker_Position_{X,Y,Z}
    """
    n_frames = len(df)
    markers = np.full((n_frames, len(BODY_MARKER_NAMES), 3), np.nan, dtype=np.float32)

    found = 0
    missing = []

    for i, name in enumerate(BODY_MARKER_NAMES):
        x_col = f'{skeleton_prefix}:{name}_Marker_Position_X'
        y_col = f'{skeleton_prefix}:{name}_Marker_Position_Y'
        z_col = f'{skeleton_prefix}:{name}_Marker_Position_Z'

        if x_col in df.columns and y_col in df.columns and z_col in df.columns:
            markers[:, i, 0] = df[x_col].values.astype(np.float32)
            markers[:, i, 1] = df[y_col].values.astype(np.float32)
            markers[:, i, 2] = df[z_col].values.astype(np.float32)
            found += 1
        else:
            missing.append(name)

    print(f"  Body markers: {found}/{len(BODY_MARKER_NAMES)} found")
    if missing:
        print(f"  Missing: {', '.join(missing)}")

    return markers


def extract_leg_markers(df):
    """
    Extract leg markers (L1-L4, R1-R4) as (N, M, 3) array.

    Uses suffix-based search to handle different markerset naming.
    Returns only markers that exist in the dataset.
    """
    n_frames = len(df)
    found_markers = []
    found_names = []

    for suffix in LEG_MARKER_SUFFIXES:
        # Try Marker type first, then Rigid Body Marker
        for marker_type in ['Marker', 'Rigid Body Marker']:
            base, cols = find_marker_columns_by_suffix(df, suffix, marker_type)
            if cols is not None:
                data = np.stack([
                    df[cols[0]].values.astype(np.float32),
                    df[cols[1]].values.astype(np.float32),
                    df[cols[2]].values.astype(np.float32),
                ], axis=1)
                found_markers.append(data)
                found_names.append(suffix)
                break

    if found_markers:
        markers = np.stack(found_markers, axis=1)  # (N, M, 3)
    else:
        markers = np.full((n_frames, 0, 3), np.nan, dtype=np.float32)

    print(f"  Leg markers: {len(found_names)} found ({', '.join(found_names)})")
    return markers, found_names


def main():
    parser = argparse.ArgumentParser(description='Extract markers from Motive CSV')
    parser.add_argument('csv_file', help='Input CSV file')
    parser.add_argument('-o', '--output-dir', type=Path,
                        help='Output directory (default: same as CSV)')
    parser.add_argument('--legs', action='store_true',
                        help='Also extract leg markers (L1-L4, R1-R4)')
    parser.add_argument('--prefix', help='Override skeleton prefix detection')
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    output_dir = args.output_dir or csv_path.parent

    print(f"Loading CSV: {csv_path}")
    df = load_motive_csv(csv_path)
    print(f"Total frames: {len(df)}")

    # Detect skeleton prefix
    if args.prefix:
        skeleton_prefix = args.prefix
    else:
        skeleton_prefix = detect_skeleton_prefix(df)
        if skeleton_prefix is None:
            print("Error: Could not detect skeleton prefix")
            return 1

    print(f"Skeleton prefix: {skeleton_prefix}")

    # Extract body markers
    body_markers = extract_body_markers(df, skeleton_prefix)

    # Save body markers
    body_markers_path = output_dir / 'body_markers.npy'
    np.save(body_markers_path, body_markers)
    print(f"  Saved: {body_markers_path} {body_markers.shape}")

    # Save marker names
    names_path = output_dir / 'body_marker_names.json'
    with open(names_path, 'w') as f:
        json.dump(BODY_MARKER_NAMES, f)
    print(f"  Saved: {names_path}")

    # NaN stats
    total_vals = body_markers.shape[0] * body_markers.shape[1]
    nan_vals = np.isnan(body_markers[:, :, 0]).sum()
    print(f"  Valid: {total_vals - nan_vals}/{total_vals} ({100*(total_vals-nan_vals)/total_vals:.1f}%)")

    # Extract leg markers
    if args.legs:
        leg_markers, leg_names = extract_leg_markers(df)

        if len(leg_names) > 0:
            leg_markers_path = output_dir / 'leg_markers.npy'
            np.save(leg_markers_path, leg_markers)
            print(f"  Saved: {leg_markers_path} {leg_markers.shape}")

            leg_names_path = output_dir / 'leg_marker_names.json'
            with open(leg_names_path, 'w') as f:
                json.dump(leg_names, f)
            print(f"  Saved: {leg_names_path}")
        else:
            print("  No leg markers found")

    return 0


if __name__ == '__main__':
    exit(main())
