#!/usr/bin/env python3
"""
One-time script to fix leg marker naming in Motive CSV exports.

Problem:
    Only P7_1 has correctly named leg markers (L1, L2, R1, R2).
    P7_2~P7_5 use generic Marker 001~005 numbering.

Verified mapping (confirmed via hardware IDs):
    Lleg:Marker 001 → Lleg:L1
    Lleg:Marker 004 → Lleg:L2
    Rleg:Marker 003 → Rleg:R1
    Rleg:Marker 004 → Rleg:R2

Only the Name header row (row index 3) is modified. Data rows are untouched.

Usage:
    # Preview changes without modifying files
    python fix_leg_marker_names.py --input_dir /Volumes/KINGSTON/P7_mocap --dry_run

    # Apply changes (creates .csv.bak backups)
    python fix_leg_marker_names.py --input_dir /Volumes/KINGSTON/P7_mocap

    # Specific sessions only
    python fix_leg_marker_names.py --input_dir /Volumes/KINGSTON/P7_mocap --sessions P7_2 P7_3
"""

import os
import sys
import shutil
import argparse
import glob
from typing import List, Dict, Tuple

# Verified mapping: generic name -> correct name
RENAME_MAP = {
    "Lleg:Marker 001": "Lleg:L1",
    "Lleg:Marker 004": "Lleg:L2",
    "Rleg:Marker 003": "Rleg:R1",
    "Rleg:Marker 004": "Rleg:R2",
}

# Row index (0-based) of the Name row in Motive CSV format 1.25
NAME_ROW_INDEX = 3


def find_csv_files(input_dir: str, sessions: List[str] = None) -> List[str]:
    """Find all session CSV files to process."""
    if sessions:
        dirs = [os.path.join(input_dir, s) for s in sessions]
    else:
        dirs = sorted(glob.glob(os.path.join(input_dir, "P*_*")))
        # Exclude P7_1 (already correct)
        dirs = [d for d in dirs if not d.endswith("P7_1")]

    csv_files = []
    for d in dirs:
        if not os.path.isdir(d):
            print(f"  WARNING: directory not found: {d}")
            continue
        csvs = sorted(glob.glob(os.path.join(d, "*.csv")))
        # Exclude backup files
        csvs = [c for c in csvs if not c.endswith(".bak")]
        csv_files.extend(csvs)

    return csv_files


def analyze_name_row(line: str) -> Dict[str, List[int]]:
    """Find columns that need renaming in the Name row.

    Returns: {old_name: [col_indices]}
    """
    fields = line.rstrip("\n").rstrip("\r").split(",")
    hits = {}
    for i, field in enumerate(fields):
        if field in RENAME_MAP:
            hits.setdefault(field, []).append(i)
    return hits


def apply_renames(line: str, hits: Dict[str, List[int]]) -> str:
    """Apply renames to the Name row."""
    fields = line.rstrip("\n").rstrip("\r").split(",")
    for old_name, indices in hits.items():
        new_name = RENAME_MAP[old_name]
        for i in indices:
            fields[i] = new_name
    return ",".join(fields) + "\n"


def process_csv(csv_path: str, dry_run: bool = False, no_backup: bool = False) -> bool:
    """Process a single CSV file.

    Returns True if changes were made (or would be made in dry_run).
    """
    session_name = os.path.basename(os.path.dirname(csv_path))
    csv_name = os.path.basename(csv_path)
    label = f"{session_name}/{csv_name}"

    # Read only the header lines we need
    with open(csv_path, "r", encoding="utf-8") as f:
        # Verify Motive format
        first_line = f.readline()
        if not first_line.startswith("Format Version"):
            print(f"  [{label}] SKIP: not a Motive CSV (no 'Format Version' header)")
            return False

        # Read up to the Name row
        header_lines = [first_line]
        for _ in range(NAME_ROW_INDEX):
            header_lines.append(f.readline())

        # header_lines[NAME_ROW_INDEX] is the Name row
        name_row = header_lines[NAME_ROW_INDEX]

    # Analyze
    hits = analyze_name_row(name_row)

    if not hits:
        print(f"  [{label}] SKIP: no markers to rename (already correct or different structure)")
        return False

    # Report
    total_cols = sum(len(v) for v in hits.values())
    print(f"  [{label}] Found {total_cols} columns to rename:")
    for old_name, indices in sorted(hits.items()):
        new_name = RENAME_MAP[old_name]
        print(f"    {old_name:25s} -> {new_name:10s}  ({len(indices)} columns: {indices[:6]}{'...' if len(indices) > 6 else ''})")

    if dry_run:
        print(f"  [{label}] DRY RUN: no changes made")
        return True

    # Create backup
    if not no_backup:
        bak_path = csv_path + ".bak"
        if not os.path.exists(bak_path):
            shutil.copy2(csv_path, bak_path)
            print(f"  [{label}] Backup: {bak_path}")
        else:
            print(f"  [{label}] Backup already exists, skipping")

    # Apply: write to local temp file (avoids disk-full on USB drives),
    # then copy back and replace the original.
    new_name_row = apply_renames(name_row, hits)
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".csv", prefix="fix_markers_")
    os.close(tmp_fd)

    try:
        with open(csv_path, "r", encoding="utf-8") as fin, \
             open(tmp_path, "w", encoding="utf-8") as fout:
            for line_idx, line in enumerate(fin):
                if line_idx == NAME_ROW_INDEX:
                    fout.write(new_name_row)
                else:
                    fout.write(line)

        # Copy back to original location and replace
        shutil.copy2(tmp_path, csv_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    print(f"  [{label}] DONE: {total_cols} columns renamed")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Fix leg marker names in Motive CSV exports (one-time)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Verified mapping (from P7_1 hardware IDs):
    Lleg:Marker 001 -> Lleg:L1
    Lleg:Marker 004 -> Lleg:L2
    Rleg:Marker 003 -> Rleg:R1
    Rleg:Marker 004 -> Rleg:R2
        """,
    )
    parser.add_argument("--input_dir", required=True,
                        help="Base directory containing P7_* session folders")
    parser.add_argument("--sessions", nargs="+", default=None,
                        help="Specific sessions to process (default: all except P7_1)")
    parser.add_argument("--dry_run", action="store_true",
                        help="Preview changes without modifying files")
    parser.add_argument("--no_backup", action="store_true",
                        help="Skip creating .csv.bak backups")

    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"ERROR: input directory not found: {args.input_dir}")
        return 1

    print("=" * 60)
    print("Fix Leg Marker Names in Motive CSV")
    print("=" * 60)
    print(f"Input dir: {args.input_dir}")
    print(f"Mode:      {'DRY RUN' if args.dry_run else 'APPLY'}")
    print(f"Backup:    {'No' if args.no_backup else 'Yes'}")
    print()

    csv_files = find_csv_files(args.input_dir, args.sessions)

    if not csv_files:
        print("No CSV files found to process.")
        return 0

    print(f"Found {len(csv_files)} CSV file(s):")
    for f in csv_files:
        print(f"  {f}")
    print()

    modified = 0
    for csv_path in csv_files:
        if process_csv(csv_path, dry_run=args.dry_run, no_backup=args.no_backup):
            modified += 1
        print()

    print("=" * 60)
    print(f"Summary: {modified}/{len(csv_files)} files {'would be modified' if args.dry_run else 'modified'}")
    if args.dry_run and modified > 0:
        print("  Run without --dry_run to apply changes.")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
