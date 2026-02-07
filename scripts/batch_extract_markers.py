#!/usr/bin/env python3
"""
Batch extract body markers from Motive CSV for P4-P6 datasets.

For each dataset, extracts body_markers.npy (27 Plug-in Gait markers)
and optionally leg_markers.npy (L1-L4, R1-R4).

Usage:
    python batch_extract_markers.py --base /Volumes/T7/csl
    python batch_extract_markers.py --base /Volumes/T7/csl --legs
    python batch_extract_markers.py --base /Volumes/T7/csl --only P4_1,P4_2
    python batch_extract_markers.py --base /Volumes/T7/csl --dry-run
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(
        description='Batch extract body markers from Motive CSV')
    parser.add_argument('--base', required=True, type=Path,
                        help='Base directory containing P4_*/P5_*/P6_* folders')
    parser.add_argument('--structures', type=Path,
                        help='Path to csv_structures.json')
    parser.add_argument('--only', help='Only process these datasets (comma-separated)')
    parser.add_argument('--skip', help='Skip these datasets (comma-separated)')
    parser.add_argument('--legs', action='store_true',
                        help='Also extract leg markers (L1-L4, R1-R4)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print commands without executing')
    args = parser.parse_args()

    # Load csv_structures.json
    structures_file = args.structures or args.base / 'csv_structures.json'
    if not structures_file.exists():
        print(f"Error: {structures_file} not found")
        return 1

    with open(structures_file) as f:
        structures = json.load(f)

    # Parse filters
    only_datasets = set(args.only.split(',')) if args.only else None
    skip_datasets = set(args.skip.split(',')) if args.skip else set()
    skip_datasets.add('P5_1')  # Always skip (no L/R naming)

    script_dir = Path(__file__).parent
    extract_script = script_dir / 'extract_markers.py'

    print(f"Base: {args.base}")
    print(f"Datasets: {len(structures['datasets'])}")
    print(f"Skip: {skip_datasets}")
    print()

    results = {'extract_ok': 0, 'extract_fail': 0, 'skipped': 0}

    for dataset in structures['datasets']:
        name = dataset['directory']
        csv_file = dataset['csv_file']

        if only_datasets and name not in only_datasets:
            continue
        if name in skip_datasets:
            print(f"[SKIP] {name}")
            results['skipped'] += 1
            continue

        data_dir = args.base / name
        csv_path = data_dir / csv_file

        print(f"[{name}]")

        if not csv_path.exists():
            print(f"  [SKIP] CSV not found: {csv_path}")
            results['skipped'] += 1
            continue

        cmd = [
            sys.executable, str(extract_script),
            str(csv_path),
            '-o', str(data_dir),
        ]
        if args.legs:
            cmd.append('--legs')

        print(f"  Extracting markers...")
        if args.dry_run:
            print(f"  CMD: {' '.join(cmd)}")
        else:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                # Show key output lines
                for line in result.stdout.strip().split('\n'):
                    if 'Saved:' in line or 'Valid:' in line or 'Missing:' in line:
                        print(f"  {line.strip()}")
                results['extract_ok'] += 1
            else:
                print(f"  [FAIL] Extract failed")
                if result.stderr:
                    for line in result.stderr.strip().split('\n')[-3:]:
                        print(f"    {line}")
                results['extract_fail'] += 1

        print()

    # Summary
    print("=" * 60)
    print("Summary:")
    print(f"  Extract OK:   {results['extract_ok']}")
    print(f"  Extract Fail: {results['extract_fail']}")
    print(f"  Skipped:      {results['skipped']}")
    print("=" * 60)

    return 0 if results['extract_fail'] == 0 else 1


if __name__ == '__main__':
    exit(main())
