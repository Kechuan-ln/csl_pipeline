#!/usr/bin/env python3
"""
Extract blade edges from OptiTrack CSV using edge ordering from blade_polygon_order.json.
Produces blade_edge1.npy, blade_edge2.npy, and aligned_edges.npy (arc-length resampled).

Auto-detects blade rigid body name from csv_structures.json.

Usage:
    python extract_blade_edges.py --base /Volumes/T7/csl --dataset P4_1
    python extract_blade_edges.py --csv path/to/file.csv --rigid-body Blade --json path/to/order.json -o output_dir

Output files:
    - blade_edge1.npy (N_frames, N_edge1, 3)
    - blade_edge2.npy (N_frames, N_edge2, 3)
    - aligned_edges.npy (N_frames, N_resampled, 2, 3) - arc-length aligned pairs
    - blade_marker_names.json
"""

import csv
import json
import numpy as np
from pathlib import Path
import sys
import argparse


def find_blade_rb(dataset_info):
    """Find blade rigid body name from dataset info."""
    rb_names = dataset_info.get('summary', {}).get('rigid_body_names', [])
    for name in rb_names:
        if 'blade' in name.lower():
            markers = dataset_info['assets']['rigid_bodies'][name].get('markers', [])
            return name, len(markers)
    return None, 0


def resample_edge_by_arc_length(points, n_samples):
    """Resample edge to n_samples points at uniform arc-length positions."""
    if np.any(np.isnan(points)):
        return np.full((n_samples, 3), np.nan, dtype=np.float32)

    n_input = len(points)
    if n_input < 2:
        return np.full((n_samples, 3), np.nan, dtype=np.float32)

    if n_input == n_samples:
        return points.copy()

    dists = np.linalg.norm(np.diff(points, axis=0), axis=1)
    arc_length = np.concatenate([[0], np.cumsum(dists)])
    total_length = arc_length[-1]

    if total_length < 1e-6:
        return np.full((n_samples, 3), np.nan, dtype=np.float32)

    arc_length_norm = arc_length / total_length
    s_new = np.linspace(0, 1, n_samples)

    resampled = np.zeros((n_samples, 3), dtype=np.float32)
    for dim in range(3):
        resampled[:, dim] = np.interp(s_new, arc_length_norm, points[:, dim])

    return resampled


def parse_csv_headers(csv_path, rigid_body_name):
    """Parse Motive CSV headers to find Marker columns (raw observed positions)."""
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        rows = [next(reader) for _ in range(8)]

    types = rows[2]
    names = rows[3]
    props = rows[6]
    axes = rows[7]

    marker_cols = {}
    i = 0
    while i < len(names):
        name = names[i]
        if (rigid_body_name in name and ':Marker' in name and
                types[i] == 'Rigid Body Marker' and props[i] == 'Position'):
            marker_name = name.split(':')[1]  # "Marker 001"
            if (i + 2 < len(names) and
                    axes[i] == 'X' and axes[i+1] == 'Y' and axes[i+2] == 'Z'):
                marker_cols[marker_name] = {'X': i, 'Y': i+1, 'Z': i+2}
                i += 3
                continue
        i += 1

    return marker_cols


def extract_edge_frames(csv_path, marker_cols, edge_markers):
    """Extract all frames for markers in edge order."""
    col_indices = []
    valid_markers = []
    for marker_name in edge_markers:
        if marker_name in marker_cols:
            cols = marker_cols[marker_name]
            col_indices.append((cols['X'], cols['Y'], cols['Z']))
            valid_markers.append(marker_name)
        else:
            print(f"  Warning: {marker_name} not found in CSV")

    all_frames = []
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        for _ in range(8):
            next(reader)

        for row_idx, row in enumerate(reader):
            if row_idx % 10000 == 0:
                print(f"  Frame {row_idx}...")

            frame_data = []
            for x_idx, y_idx, z_idx in col_indices:
                try:
                    x = float(row[x_idx]) if row[x_idx] else np.nan
                    y = float(row[y_idx]) if row[y_idx] else np.nan
                    z = float(row[z_idx]) if row[z_idx] else np.nan
                    frame_data.append([x, y, z])
                except (IndexError, ValueError):
                    frame_data.append([np.nan, np.nan, np.nan])

            all_frames.append(frame_data)

    return np.array(all_frames, dtype=np.float32), valid_markers


def find_segment_csvs(data_dir):
    """Find segment CSVs for P5_4-style split exports.

    Returns list of (csv_path, start_frame, end_frame) sorted by start_frame,
    or empty list if no segments found.
    Segment filenames: *_START_END.csv or *_START_end.csv
    """
    import re
    segments = []
    for p in sorted(data_dir.glob("*_*.csv")):
        if '_merged' in p.name:
            continue
        m = re.search(r'_(\d+)_(\d+)\.csv$', p.name)
        if m:
            segments.append((p, int(m.group(1)), int(m.group(2))))
            continue
        m = re.search(r'_(\d+)_end\.csv$', p.name)
        if m:
            segments.append((p, int(m.group(1)), None))  # end unknown
    segments.sort(key=lambda x: x[1])
    return segments


def extract_from_segments(data_dir, rb_name, edge_markers, total_frames):
    """Extract edge data from segment CSVs, concatenating into total_frames array.

    Handles overlapping boundaries and gaps (filled with NaN).
    """
    segments = find_segment_csvs(data_dir)
    if not segments:
        return None, []

    # Verify segments have the blade RB Marker columns
    test_cols = parse_csv_headers(segments[0][0], rb_name)
    if len(test_cols) == 0:
        return None, []

    n_markers = len(edge_markers)
    result = np.full((total_frames, n_markers, 3), np.nan, dtype=np.float32)
    valid_markers = None

    for seg_path, start, end in segments:
        print(f"    Segment: {seg_path.name} (start={start})")
        marker_cols = parse_csv_headers(seg_path, rb_name)
        seg_data, seg_valid = extract_edge_frames(seg_path, marker_cols, edge_markers)
        if valid_markers is None:
            valid_markers = seg_valid

        n_seg = seg_data.shape[0]
        # Place segment data at correct position, skip first row if overlapping
        write_start = start
        data_offset = 0
        if start > 0 and start < total_frames and not np.all(np.isnan(result[start])):
            # Overlap: skip first frame of this segment
            write_start = start + 1
            data_offset = 1

        write_end = min(write_start + n_seg - data_offset, total_frames)
        n_write = write_end - write_start
        if n_write > 0:
            result[write_start:write_end] = seg_data[data_offset:data_offset + n_write]
            print(f"    Placed frames {write_start}-{write_end-1} ({n_write} frames)")

    return result, valid_markers or []


def process_dataset(base_dir, dataset_info, output_dir=None):
    """Extract blade edges for a single dataset.

    Returns (success, message).
    """
    name = dataset_info['directory']
    data_dir = base_dir / name
    csv_file = dataset_info['csv_file']
    csv_path = data_dir / csv_file
    out_dir = Path(output_dir) if output_dir else data_dir

    # Find blade RB
    rb_name, n_markers = find_blade_rb(dataset_info)
    if rb_name is None:
        return False, "No blade rigid body found"

    # Find polygon order JSON
    json_path = data_dir / 'blade_polygon_order.json'
    if not json_path.exists():
        return False, "blade_polygon_order.json not found"

    with open(json_path) as f:
        order_data = json.load(f)

    edge1_markers = order_data['edge1']
    edge2_markers = order_data['edge2']

    print(f"  Blade RB: {rb_name}")
    print(f"  Edge 1: {len(edge1_markers)} markers, Edge 2: {len(edge2_markers)} markers")

    # Check if main CSV has blade RB Marker columns
    use_segments = False
    if csv_path.exists():
        marker_cols = parse_csv_headers(csv_path, rb_name)
        if len(marker_cols) == 0:
            print(f"  Main CSV has 0 Rigid Body Marker columns for blade")
            use_segments = True
        else:
            print(f"  Found {len(marker_cols)} markers in CSV")
    else:
        use_segments = True

    if use_segments:
        # Try segment-based extraction (P5_4 case)
        segments = find_segment_csvs(data_dir)
        if not segments:
            if not csv_path.exists():
                return False, f"CSV not found and no segments: {csv_path}"
            return False, f"Blade RB '{rb_name}' has 0 markers in main CSV, no segments found"

        # Determine total frames from merged CSV row count
        if csv_path.exists():
            with open(csv_path, 'r') as f:
                reader = csv.reader(f)
                for _ in range(8):
                    next(reader)
                total_frames = sum(1 for _ in reader)
        else:
            # Estimate from segments
            last_seg = segments[-1]
            total_frames = last_seg[1]  # start of last segment
            with open(last_seg[0], 'r') as f:
                reader = csv.reader(f)
                for _ in range(8):
                    next(reader)
                total_frames += sum(1 for _ in reader)

        print(f"  Using {len(segments)} segment CSVs ({total_frames} total frames)")

        print(f"  Extracting Edge 1 from segments...")
        edge1_data, edge1_valid = extract_from_segments(
            data_dir, rb_name, edge1_markers, total_frames)
        if edge1_data is None:
            return False, "Failed to extract Edge 1 from segments"
        print(f"  Edge 1: {edge1_data.shape}")

        print(f"  Extracting Edge 2 from segments...")
        edge2_data, edge2_valid = extract_from_segments(
            data_dir, rb_name, edge2_markers, total_frames)
        if edge2_data is None:
            return False, "Failed to extract Edge 2 from segments"
        print(f"  Edge 2: {edge2_data.shape}")
    else:
        # Normal single-CSV extraction
        print(f"  Extracting Edge 1...")
        edge1_data, edge1_valid = extract_edge_frames(csv_path, marker_cols, edge1_markers)
        print(f"  Edge 1: {edge1_data.shape}")

        print(f"  Extracting Edge 2...")
        edge2_data, edge2_valid = extract_edge_frames(csv_path, marker_cols, edge2_markers)
        print(f"  Edge 2: {edge2_data.shape}")

    # Arc-length resampling for aligned_edges
    n_frames = edge1_data.shape[0]
    n1, n2 = len(edge1_valid), len(edge2_valid)
    n_target = max(n1, n2)

    print(f"  Arc-length resampling: {n1} x {n2} -> {n_target} pairs, {n_frames} frames")

    aligned_edges = np.zeros((n_frames, n_target, 2, 3), dtype=np.float32)

    for i in range(n_frames):
        if i % 10000 == 0:
            print(f"  Resampling frame {i}...")

        e1_resampled = resample_edge_by_arc_length(edge1_data[i], n_target)
        e2_resampled = resample_edge_by_arc_length(edge2_data[i], n_target)
        aligned_edges[i, :, 0, :] = e1_resampled
        aligned_edges[i, :, 1, :] = e2_resampled

    # Save outputs
    edge1_path = out_dir / "blade_edge1.npy"
    edge2_path = out_dir / "blade_edge2.npy"
    aligned_path = out_dir / "blade_edges.npy"
    names_path = out_dir / "blade_marker_names.json"

    np.save(edge1_path, edge1_data)
    np.save(edge2_path, edge2_data)
    np.save(aligned_path, aligned_edges)

    with open(names_path, 'w') as f:
        json.dump({
            'rigid_body': rb_name,
            'edge1': edge1_valid,
            'edge2': edge2_valid,
            'n_resampled': n_target,
        }, f, indent=2)

    # Statistics
    nan_e1 = np.sum(np.any(np.isnan(edge1_data), axis=(1, 2)))
    nan_e2 = np.sum(np.any(np.isnan(edge2_data), axis=(1, 2)))

    print(f"  Saved:")
    print(f"    Edge 1: {edge1_path.name} - {edge1_data.shape}")
    print(f"    Edge 2: {edge2_path.name} - {edge2_data.shape}")
    print(f"    Aligned: {aligned_path.name} - {aligned_edges.shape}")
    print(f"    Names: {names_path.name}")
    print(f"  Missing data: Edge1={nan_e1}/{n_frames} ({100*nan_e1/n_frames:.1f}%), "
          f"Edge2={nan_e2}/{n_frames} ({100*nan_e2/n_frames:.1f}%)")

    return True, f"aligned_edges.npy {aligned_edges.shape}"


def main():
    parser = argparse.ArgumentParser(
        description='Extract blade edges from OptiTrack CSV')
    parser.add_argument('--base', type=Path,
                        help='Base directory containing P4_*/P5_*/P6_* folders')
    parser.add_argument('--dataset', type=str,
                        help='Single dataset to process (e.g., P4_1)')
    parser.add_argument('--csv', type=Path,
                        help='Direct CSV file path')
    parser.add_argument('--rigid-body', type=str, default=None,
                        help='Rigid body name (auto-detected if --base used)')
    parser.add_argument('--json', type=Path, default=None,
                        help='Path to blade_polygon_order.json')
    parser.add_argument('-o', '--output', type=Path, default=None,
                        help='Output directory')
    parser.add_argument('--structures', type=Path,
                        help='Path to csv_structures.json')
    args = parser.parse_args()

    # Mode 1: Direct CSV + JSON
    if args.csv:
        if not args.csv.exists():
            print(f"Error: CSV not found: {args.csv}")
            return 1

        rb_name = args.rigid_body or 'Blade'
        json_path = args.json or args.csv.parent / 'blade_polygon_order.json'
        out_dir = args.output or args.csv.parent

        if not json_path.exists():
            print(f"Error: {json_path} not found")
            return 1

        with open(json_path) as f:
            order_data = json.load(f)

        marker_cols = parse_csv_headers(args.csv, rb_name)
        print(f"Found {len(marker_cols)} markers for '{rb_name}'")

        edge1_markers = order_data['edge1']
        edge2_markers = order_data['edge2']

        print(f"Extracting Edge 1 ({len(edge1_markers)} markers)...")
        edge1_data, edge1_valid = extract_edge_frames(args.csv, marker_cols, edge1_markers)
        print(f"Edge 1: {edge1_data.shape}")

        print(f"Extracting Edge 2 ({len(edge2_markers)} markers)...")
        edge2_data, edge2_valid = extract_edge_frames(args.csv, marker_cols, edge2_markers)
        print(f"Edge 2: {edge2_data.shape}")

        n_frames = edge1_data.shape[0]
        n1, n2 = len(edge1_valid), len(edge2_valid)
        n_target = max(n1, n2)

        print(f"Arc-length resampling: {n1} x {n2} -> {n_target} pairs")

        aligned_edges = np.zeros((n_frames, n_target, 2, 3), dtype=np.float32)
        for i in range(n_frames):
            if i % 10000 == 0:
                print(f"  Resampling frame {i}...")
            e1 = resample_edge_by_arc_length(edge1_data[i], n_target)
            e2 = resample_edge_by_arc_length(edge2_data[i], n_target)
            aligned_edges[i, :, 0, :] = e1
            aligned_edges[i, :, 1, :] = e2

        out_dir = Path(out_dir)
        np.save(out_dir / "blade_edge1.npy", edge1_data)
        np.save(out_dir / "blade_edge2.npy", edge2_data)
        np.save(out_dir / "blade_edges.npy", aligned_edges)

        with open(out_dir / "blade_marker_names.json", 'w') as f:
            json.dump({
                'rigid_body': rb_name,
                'edge1': edge1_valid,
                'edge2': edge2_valid,
                'n_resampled': n_target,
            }, f, indent=2)

        print(f"\nSaved to {out_dir}:")
        print(f"  blade_edge1.npy: {edge1_data.shape}")
        print(f"  blade_edge2.npy: {edge2_data.shape}")
        print(f"  aligned_edges.npy: {aligned_edges.shape}")
        return 0

    # Mode 2: Use csv_structures.json
    if args.base is None or args.dataset is None:
        print("Error: --base + --dataset or --csv required")
        return 1

    structures_file = args.structures or args.base / 'csv_structures.json'
    if not structures_file.exists():
        print(f"Error: {structures_file} not found")
        return 1

    with open(structures_file) as f:
        structures = json.load(f)

    ds_lookup = {d['directory']: d for d in structures['datasets']}
    if args.dataset not in ds_lookup:
        print(f"Error: Dataset '{args.dataset}' not found")
        return 1

    ds = ds_lookup[args.dataset]
    print(f"[{args.dataset}]")
    ok, msg = process_dataset(args.base, ds, args.output)
    print(f"{'[OK]' if ok else '[FAIL]'} {msg}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
