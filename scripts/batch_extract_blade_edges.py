#!/usr/bin/env python3
"""
Batch extract blade edges for P4-P6 datasets.

For each dataset:
    - If no blade_polygon_order.json: report as needing manual edge definition
    - If blade_polygon_order.json exists: extract blade edges + blade_edges.npy

Usage:
    python batch_extract_blade_edges.py --base /Volumes/T7/csl
    python batch_extract_blade_edges.py --base /Volumes/T7/csl --only P4_1,P4_2
    python batch_extract_blade_edges.py --base /Volumes/T7/csl --dry-run
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys


def find_blade_rb(dataset_info):
    """Find blade rigid body name and marker count."""
    rb_names = dataset_info.get('summary', {}).get('rigid_body_names', [])
    for name in rb_names:
        if 'blade' in name.lower():
            markers = dataset_info['assets']['rigid_bodies'][name].get('markers', [])
            return name, len(markers)
    return None, 0


def main():
    parser = argparse.ArgumentParser(
        description='Batch extract blade edges for P4-P6 datasets')
    parser.add_argument('--base', required=True, type=Path,
                        help='Base directory containing P4_*/P5_*/P6_* folders')
    parser.add_argument('--structures', type=Path,
                        help='Path to csv_structures.json')
    parser.add_argument('--only', help='Only process these datasets (comma-separated)')
    parser.add_argument('--skip', help='Skip these datasets (comma-separated)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print actions without executing')
    args = parser.parse_args()

    structures_file = args.structures or args.base / 'csv_structures.json'
    if not structures_file.exists():
        print(f"Error: {structures_file} not found")
        return 1

    with open(structures_file) as f:
        structures = json.load(f)

    only_datasets = set(args.only.split(',')) if args.only else None
    skip_datasets = set(args.skip.split(',')) if args.skip else set()

    script_dir = Path(__file__).parent
    extract_script = script_dir / 'extract_blade_edges.py'

    print(f"Base: {args.base}")
    print(f"Datasets: {len(structures['datasets'])}")
    if skip_datasets:
        print(f"Skip: {skip_datasets}")
    print()

    results = {
        'extract_ok': 0, 'extract_fail': 0,
        'no_blade': 0, 'no_markers': 0,
        'has_json': 0, 'has_aligned': 0,
        'skipped': 0,
    }
    needs_editor = []

    for dataset in structures['datasets']:
        name = dataset['directory']

        if only_datasets and name not in only_datasets:
            continue
        if name in skip_datasets:
            print(f"[SKIP] {name}")
            results['skipped'] += 1
            continue

        data_dir = args.base / name

        # Check blade RB
        rb_name, n_markers = find_blade_rb(dataset)
        if rb_name is None:
            print(f"[SKIP] {name}: no blade rigid body")
            results['no_blade'] += 1
            continue
        if n_markers == 0:
            # Check for segment CSVs (P5_4 case)
            import re
            seg_csvs = [p for p in sorted(data_dir.glob("*_*.csv"))
                        if '_merged' not in p.name and
                        (re.search(r'_\d+_\d+\.csv$', p.name) or
                         re.search(r'_\d+_end\.csv$', p.name))]
            if not seg_csvs:
                print(f"[SKIP] {name}: blade RB '{rb_name}' has 0 markers, no segments")
                results['no_markers'] += 1
                continue
            print(f"[{name}] blade={rb_name} (0 markers in merged, {len(seg_csvs)} segments)")
            n_markers = -1  # flag: use segments

        has_json = (data_dir / 'blade_polygon_order.json').exists()
        has_aligned = (data_dir / 'blade_edges.npy').exists()

        if n_markers >= 0:
            print(f"[{name}] blade={rb_name} ({n_markers} markers) "
                  f"json={'Y' if has_json else 'N'} aligned={'Y' if has_aligned else 'N'}")

        if has_json:
            results['has_json'] += 1
        if has_aligned:
            results['has_aligned'] += 1

        if not has_json:
            needs_editor.append(name)
            print(f"  [NEED] blade_polygon_order.json required")
        elif has_aligned:
            print(f"  [DONE] Already processed")
        else:
            # Extract edges
            if args.dry_run:
                print(f"  DRY-RUN: would extract blade edges")
            else:
                cmd = [
                    sys.executable, str(extract_script),
                    '--base', str(args.base),
                    '--dataset', name,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    stdout_lines = result.stdout.strip().split('\n')
                    for line in stdout_lines[-3:]:
                        if 'aligned_edges' in line.lower() or '[OK]' in line:
                            print(f"  {line.strip()}")
                    results['extract_ok'] += 1
                else:
                    print(f"  [FAIL] Edge extraction failed")
                    if result.stderr:
                        for line in result.stderr.strip().split('\n')[-3:]:
                            print(f"    {line}")
                    results['extract_fail'] += 1

        print()

    # Summary
    print("=" * 60)
    print("Summary:")
    print(f"  No blade RB:      {results['no_blade']}")
    print(f"  No blade markers:  {results['no_markers']}")
    print(f"  Skipped:           {results['skipped']}")
    print(f"  Edges extracted:   {results['extract_ok']}")
    print(f"  Edges failed:      {results['extract_fail']}")
    print(f"  Already done:      {results['has_aligned']}")
    print()

    if needs_editor:
        print(f"Datasets needing edge definition: {', '.join(needs_editor)}")
        print("  1. Use polygon_editor.html to define edge1 and edge2")
        print("  2. Export blade_polygon_order.json to the dataset folder")
        print("  3. Re-run this script")

    print("=" * 60)
    return 0 if results['extract_fail'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
