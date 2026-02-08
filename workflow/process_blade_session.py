#!/usr/bin/env python3
"""
Blade edge extraction from mocap sessions.

For each session, finds blade polygon order JSONs and extracts edge trajectories
from the corresponding CSV. Produces per-blade edge .npy files.

Prerequisites:
    - process_mocap_session.py has been run (CSV exists, HTMLs generated)
    - blade_polygon_order_{blade}.json has been created via the HTML editor
      and placed in each session's output directory

Usage:
    # Process all sessions under a parent directory
    python process_blade_session.py /Volumes/KINGSTON/P7_mocap -o /Volumes/KINGSTON/P7_output --batch

    # Process single session
    python process_blade_session.py /Volumes/KINGSTON/P7_mocap/P7_1 -o /Volumes/KINGSTON/P7_output/P7_1

    # Copy JSON from one session to all others, then extract
    python process_blade_session.py /Volumes/KINGSTON/P7_mocap -o /Volumes/KINGSTON/P7_output --batch --share_json P7_1
"""

import os
import sys
import glob
import json
import shutil
import argparse
from pathlib import Path

# Add csl_pipeline paths for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSL_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(CSL_ROOT, "scripts"))

from extract_blade_edges import (
    parse_csv_headers,
    extract_edge_frames,
    resample_edge_by_arc_length,
)
import numpy as np


def find_blade_jsons(output_dir):
    """Find all blade_polygon_order_*.json files in output directory.

    Returns dict: {blade_name: json_path}
    """
    blades = {}
    for jp in sorted(glob.glob(os.path.join(output_dir, "blade_polygon_order_*.json"))):
        # Extract blade name from filename: blade_polygon_order_{name}.json
        fname = os.path.basename(jp)
        name = fname.replace("blade_polygon_order_", "").replace(".json", "")
        blades[name] = jp
    return blades


def find_session_csv(session_dir):
    """Find the CSV file in a session directory."""
    csv_files = sorted(glob.glob(os.path.join(session_dir, "*.csv")))
    csv_files = [c for c in csv_files if not c.endswith(".bak")]
    if not csv_files:
        return None
    return csv_files[0]


def process_blade(csv_path, json_path, blade_name, output_dir):
    """Extract edges for a single blade from CSV using polygon order JSON.

    Returns (success, message).
    """
    blade_safe = blade_name.replace(" ", "_")
    prefix = f"{blade_safe}_" if blade_name.lower() != "blade" else "blade_"

    # Check if already done
    edges_path = os.path.join(output_dir, f"{prefix}edges.npy")
    if os.path.exists(edges_path):
        size_mb = os.path.getsize(edges_path) / (1024 * 1024)
        return True, f"already exists ({size_mb:.1f} MB)"

    # Load JSON
    with open(json_path) as f:
        order_data = json.load(f)

    rb_name = order_data.get("rigid_body", blade_name)
    edge1_markers = order_data["edge1"]
    edge2_markers = order_data["edge2"]

    # Parse CSV headers
    marker_cols = parse_csv_headers(csv_path, rb_name)
    if not marker_cols:
        return False, f"no markers found for '{rb_name}' in CSV"

    # Extract edges
    print(f"    Extracting Edge 1 ({len(edge1_markers)} markers)...")
    edge1_data, edge1_valid = extract_edge_frames(csv_path, marker_cols, edge1_markers)

    print(f"    Extracting Edge 2 ({len(edge2_markers)} markers)...")
    edge2_data, edge2_valid = extract_edge_frames(csv_path, marker_cols, edge2_markers)

    n_frames = edge1_data.shape[0]
    n1, n2 = len(edge1_valid), len(edge2_valid)
    n_target = max(n1, n2)

    # Arc-length resample
    print(f"    Resampling: {n1} x {n2} -> {n_target} pairs, {n_frames} frames")
    aligned_edges = np.zeros((n_frames, n_target, 2, 3), dtype=np.float32)
    for i in range(n_frames):
        if i % 10000 == 0 and i > 0:
            print(f"      frame {i}/{n_frames}...")
        e1 = resample_edge_by_arc_length(edge1_data[i], n_target)
        e2 = resample_edge_by_arc_length(edge2_data[i], n_target)
        aligned_edges[i, :, 0, :] = e1
        aligned_edges[i, :, 1, :] = e2

    # Save
    out = Path(output_dir)
    np.save(out / f"{prefix}edge1.npy", edge1_data)
    np.save(out / f"{prefix}edge2.npy", edge2_data)
    np.save(out / f"{prefix}edges.npy", aligned_edges)

    with open(out / f"{prefix}marker_names.json", "w") as f:
        json.dump({
            "rigid_body": rb_name,
            "edge1": edge1_valid,
            "edge2": edge2_valid,
            "n_resampled": n_target,
        }, f, indent=2)

    # Stats
    nan_e1 = np.sum(np.any(np.isnan(edge1_data), axis=(1, 2)))
    nan_e2 = np.sum(np.any(np.isnan(edge2_data), axis=(1, 2)))

    return True, (
        f"edges={aligned_edges.shape}, "
        f"missing: e1={nan_e1}/{n_frames} ({100*nan_e1/n_frames:.1f}%), "
        f"e2={nan_e2}/{n_frames} ({100*nan_e2/n_frames:.1f}%)"
    )


def process_session(session_dir, output_dir):
    """Process all blades for a single session.

    Returns (n_success, n_total).
    """
    session_name = os.path.basename(output_dir)

    # Find CSV
    csv_path = find_session_csv(session_dir)
    if csv_path is None:
        print(f"  ERROR: No CSV found in {session_dir}")
        return 0, 0

    # Find blade JSONs
    blades = find_blade_jsons(output_dir)
    if not blades:
        print(f"  No blade_polygon_order_*.json found in {output_dir}")
        return 0, 0

    print(f"  CSV: {os.path.basename(csv_path)}")
    print(f"  Blades: {', '.join(blades.keys())}")

    n_success = 0
    for blade_name, json_path in blades.items():
        print(f"\n  [{blade_name}]")
        ok, msg = process_blade(csv_path, json_path, blade_name, output_dir)
        status = "OK" if ok else "FAIL"
        print(f"  [{blade_name}] {status}: {msg}")
        if ok:
            n_success += 1

    return n_success, len(blades)


def share_jsons(source_output, all_output_dirs):
    """Copy blade JSONs from source session to all other sessions."""
    jsons = glob.glob(os.path.join(source_output, "blade_polygon_order_*.json"))
    if not jsons:
        print(f"  No blade JSONs found in {source_output}")
        return

    for target_dir in all_output_dirs:
        if target_dir == source_output:
            continue
        for jp in jsons:
            dest = os.path.join(target_dir, os.path.basename(jp))
            if not os.path.exists(dest):
                shutil.copy2(jp, dest)
                print(f"  Copied {os.path.basename(jp)} -> {os.path.basename(target_dir)}/")


def main():
    parser = argparse.ArgumentParser(
        description="Blade edge extraction from mocap sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single session
  python process_blade_session.py /Volumes/KINGSTON/P7_mocap/P7_1 -o /Volumes/KINGSTON/P7_output/P7_1

  # Batch: all sessions
  python process_blade_session.py /Volumes/KINGSTON/P7_mocap -o /Volumes/KINGSTON/P7_output --batch

  # Batch + copy JSONs from P7_1 to all others first
  python process_blade_session.py /Volumes/KINGSTON/P7_mocap -o /Volumes/KINGSTON/P7_output --batch --share_json P7_1
        """,
    )
    parser.add_argument("input_dir", help="Session directory (or parent with --batch)")
    parser.add_argument("-o", "--output_dir", required=True, help="Output directory")
    parser.add_argument("--batch", action="store_true",
                        help="Process all P*_* subdirectories")
    parser.add_argument("--share_json", type=str, default=None,
                        help="Copy blade JSONs from this session to all others before processing")

    args = parser.parse_args()

    if args.batch:
        # Find all session directories
        sessions = sorted(glob.glob(os.path.join(args.input_dir, "P*_*")))
        sessions = [s for s in sessions if os.path.isdir(s)]
        if not sessions:
            print(f"No session directories found in {args.input_dir}")
            return 1

        # Build output dirs
        output_dirs = {
            os.path.basename(s): os.path.join(args.output_dir, os.path.basename(s))
            for s in sessions
        }

        # Share JSONs if requested
        if args.share_json:
            source = os.path.join(args.output_dir, args.share_json)
            if not os.path.isdir(source):
                print(f"Error: {source} does not exist")
                return 1
            print(f"Sharing blade JSONs from {args.share_json}:")
            share_jsons(source, list(output_dirs.values()))

        # Process each session
        print(f"\nProcessing {len(sessions)} sessions")
        results = {}
        for session_dir in sessions:
            name = os.path.basename(session_dir)
            out_dir = output_dirs[name]
            print(f"\n{'=' * 60}")
            print(f"  {name}")
            print(f"{'=' * 60}")
            n_ok, n_total = process_session(session_dir, out_dir)
            results[name] = (n_ok, n_total)

        # Summary
        print(f"\n{'=' * 60}")
        print("SUMMARY")
        print(f"{'=' * 60}")
        for name, (n_ok, n_total) in results.items():
            status = "OK" if n_ok == n_total else "PARTIAL" if n_ok > 0 else "FAIL"
            print(f"  {name}: {status} ({n_ok}/{n_total} blades)")

        failed = sum(1 for n_ok, n_total in results.values() if n_ok < n_total)
        return 1 if failed else 0
    else:
        print(f"Processing: {args.input_dir}")
        n_ok, n_total = process_session(args.input_dir, args.output_dir)
        return 0 if n_ok == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
