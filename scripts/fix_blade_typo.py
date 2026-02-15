#!/usr/bin/env python3
"""
Fix BALDE → BLADE typo in Motive CSV files.

Usage:
    # Fix single file (overwrites original, creates .bak backup)
    python fix_blade_typo.py input.csv

    # Fix single file with custom output
    python fix_blade_typo.py input.csv -o output.csv

    # Fix all CSVs in a directory
    python fix_blade_typo.py /path/to/directory --batch
"""

import os
import sys
import argparse
import shutil
import glob


def fix_blade_typo_in_file(input_path, output_path=None, create_backup=True):
    """
    Fix BALDE → BLADE typo in a CSV file.

    Args:
        input_path: Path to input CSV
        output_path: Path to output CSV (if None, overwrites input)
        create_backup: If True and overwriting, creates .bak backup

    Returns:
        tuple: (success, num_replacements)
    """
    if output_path is None:
        output_path = input_path
        overwrite = True
    else:
        overwrite = False

    # Create backup if overwriting
    if overwrite and create_backup and os.path.exists(input_path):
        backup_path = input_path + ".bak"
        shutil.copy2(input_path, backup_path)
        print(f"  Backup created: {os.path.basename(backup_path)}")

    try:
        # Use simple string replacement (case-sensitive for accuracy)
        # Will replace BALDE with BLADE (uppercase)
        search_str = "BALDE"
        replace_str = "BLADE"

        total_replacements = 0
        temp_path = output_path + ".tmp"

        with open(input_path, 'r', encoding='utf-8') as fin, \
             open(temp_path, 'w', encoding='utf-8', newline='') as fout:

            for line_num, line in enumerate(fin, 1):
                # Count how many times BALDE appears in this line
                count = line.count(search_str)
                if count > 0:
                    total_replacements += count

                # Replace all occurrences
                fixed_line = line.replace(search_str, replace_str)
                fout.write(fixed_line)

        # Move temp file to output
        shutil.move(temp_path, output_path)

        return True, total_replacements

    except Exception as e:
        print(f"  ERROR: {e}")
        # Clean up temp file if it exists
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False, 0


def process_single_file(input_path, output_path=None):
    """Process a single CSV file."""
    if not os.path.exists(input_path):
        print(f"ERROR: File not found: {input_path}")
        return False

    print(f"\nProcessing: {os.path.basename(input_path)}")
    success, num_replacements = fix_blade_typo_in_file(input_path, output_path)

    if success:
        if num_replacements > 0:
            print(f"  ✓ Fixed {num_replacements} occurrences of 'BALDE' → 'BLADE'")
            if output_path:
                print(f"  ✓ Saved to: {output_path}")
        else:
            print(f"  ✓ No typos found (file unchanged)")
    else:
        print(f"  ✗ FAILED")

    return success


def process_directory(dir_path):
    """Process all CSV files in a directory."""
    csv_files = glob.glob(os.path.join(dir_path, "*.csv"))

    # Exclude backup files
    csv_files = [f for f in csv_files if not f.endswith('.bak')]

    if not csv_files:
        print(f"No CSV files found in {dir_path}")
        return 0

    print(f"Found {len(csv_files)} CSV file(s) in {dir_path}")

    results = {}
    for csv_path in sorted(csv_files):
        success = process_single_file(csv_path)
        results[csv_path] = success

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    succeeded = sum(1 for ok in results.values() if ok)
    failed = len(results) - succeeded
    print(f"  Processed: {len(results)} files")
    print(f"  Success: {succeeded}")
    print(f"  Failed: {failed}")

    return 0 if failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="Fix BALDE → BLADE typo in Motive CSV files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fix single file (creates .bak backup, overwrites original)
  python fix_blade_typo.py session1.csv

  # Fix single file with custom output
  python fix_blade_typo.py session1.csv -o session1_fixed.csv

  # Fix all CSVs in a directory
  python fix_blade_typo.py /Volumes/KINGSTON/P7_mocap --batch

  # Fix without creating backup
  python fix_blade_typo.py session1.csv --no-backup
        """
    )
    parser.add_argument("input", help="Input CSV file or directory (with --batch)")
    parser.add_argument("-o", "--output", help="Output CSV file (only for single file mode)")
    parser.add_argument("--batch", action="store_true",
                       help="Process all CSV files in input directory")
    parser.add_argument("--no-backup", action="store_true",
                       help="Don't create .bak backup when overwriting")

    args = parser.parse_args()

    if args.batch:
        if not os.path.isdir(args.input):
            print(f"ERROR: {args.input} is not a directory")
            return 1
        if args.output:
            print("WARNING: --output is ignored in batch mode")
        return process_directory(args.input)
    else:
        if os.path.isdir(args.input):
            print(f"ERROR: {args.input} is a directory. Use --batch to process directories.")
            return 1

        create_backup = not args.no_backup
        success = process_single_file(args.input, args.output)
        return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
