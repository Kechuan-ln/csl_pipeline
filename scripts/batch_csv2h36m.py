#!/usr/bin/env python3
"""
Batch process P4-P6 datasets to H36M format.

Reads csv_structures.json to find all CSV files and processes them
using the universal csv2h36m.py script.

Usage:
    python batch_csv2h36m.py --base /Volumes/T7/csl
    python batch_csv2h36m.py --base /Volumes/T7/csl --dry-run
    python batch_csv2h36m.py --base /Volumes/T7/csl --only P4_1,P5_2
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description='Batch process P4-P6 datasets to H36M format')
    parser.add_argument('--base', required=True, help='Base directory containing P4_*/P5_*/P6_* folders')
    parser.add_argument('--structures', help='Path to csv_structures.json (default: base/csv_structures.json)')
    parser.add_argument('--dry-run', action='store_true', help='Print commands without executing')
    parser.add_argument('--only', help='Only process these datasets (comma-separated, e.g., P4_1,P5_2)')
    parser.add_argument('--skip', help='Skip these datasets (comma-separated)')
    parser.add_argument('--postprocess', action='store_true', help='Enable post-processing')
    parser.add_argument('--output-dir', help='Output directory (default: same as CSV)')

    args = parser.parse_args()

    base_dir = Path(args.base)
    if not base_dir.exists():
        print(f"Error: Base directory not found: {base_dir}")
        return 1

    # Load csv_structures.json
    structures_file = args.structures or base_dir / 'csv_structures.json'
    if not Path(structures_file).exists():
        print(f"Error: Structures file not found: {structures_file}")
        print("Run batch_analyze_csv.py first to generate it")
        return 1

    with open(structures_file) as f:
        structures = json.load(f)

    # Parse filters
    only_datasets = set(args.only.split(',')) if args.only else None
    skip_datasets = set(args.skip.split(',')) if args.skip else set()

    # Always skip P5_1 (no L/R naming — needs manual --amputation flag)
    skip_datasets.add('P5_1')

    print(f"Base directory: {base_dir}")
    print(f"Total datasets in structures: {len(structures['datasets'])}")
    if only_datasets:
        print(f"Only processing: {only_datasets}")
    print(f"Skipping: {skip_datasets}")
    print()

    # Find csv2h36m.py script
    script_dir = Path(__file__).parent
    csv2h36m_script = script_dir / 'csv2h36m.py'
    if not csv2h36m_script.exists():
        print(f"Error: csv2h36m.py not found at {csv2h36m_script}")
        return 1

    # Process each dataset
    success_count = 0
    fail_count = 0
    skip_count = 0

    for dataset in structures['datasets']:
        name = dataset['directory']
        csv_file = dataset['csv_file']

        # Check filters
        if only_datasets and name not in only_datasets:
            continue
        if name in skip_datasets:
            print(f"[SKIP] {name}: in skip list")
            skip_count += 1
            continue

        csv_path = base_dir / name / csv_file
        if not csv_path.exists():
            print(f"[SKIP] {name}: CSV not found: {csv_path}")
            skip_count += 1
            continue

        # Output path
        if args.output_dir:
            output_dir = Path(args.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f'{name}_skeleton_h36m.npy'
        else:
            output_file = csv_path.parent / 'skeleton_h36m.npy'

        # Build command
        cmd = [
            sys.executable, str(csv2h36m_script),
            str(csv_path),
            '-o', str(output_file),
        ]
        if args.postprocess:
            cmd.append('--postprocess')

        print(f"[{name}] Processing...")
        print(f"  Input: {csv_path}")
        print(f"  Output: {output_file}")

        if args.dry_run:
            print(f"  Command: {' '.join(cmd)}")
            continue

        # Execute
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                print(f"  [OK] Success")
                success_count += 1
            else:
                print(f"  [FAIL] Return code: {result.returncode}")
                if result.stderr:
                    print(f"  Error: {result.stderr[:500]}")
                fail_count += 1

        except Exception as e:
            print(f"  [FAIL] Exception: {e}")
            fail_count += 1

        print()

    # Summary
    print("=" * 60)
    print("Summary:")
    print(f"  Success: {success_count}")
    print(f"  Failed:  {fail_count}")
    print(f"  Skipped: {skip_count}")
    print("=" * 60)

    return 0 if fail_count == 0 else 1


if __name__ == '__main__':
    exit(main())
