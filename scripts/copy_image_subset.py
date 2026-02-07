#!/usr/bin/env python3
"""
Image subset copying utility for multical calibration datasets.

This script copies a subset of images from camera subfolders (cam0, cam1, cam2, etc.)
based on specified frame IDs. It's useful for creating smaller datasets for testing
or when you only need specific frames for calibration.

Usage:
    python copy_image_subset.py --image_path ./assets/extr_620_sync --dest_path ./assets/extr_620_sync_subset --frames 0,10,20,30,40
    
    Or modify the constants in the script and run directly:
    python copy_image_subset.py
"""

import os
import shutil
import argparse
from pathlib import Path
import re
from typing import List, Optional
import logging


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Default configuration - modify these as needed
DEFAULT_SOURCE_DIR = "../assets/videos/sync_1105/original"
DEFAULT_DEST_DIR = "../assets/videos/extr_11052"
DEFAULT_FRAME_IDS = [405, 414, 433, 443, 454, 463, 472, 483, 510, 525, 534, 544, 555, 566, 577, 587, 607, 612, 617, 629, 644, 652, 666, 690, 702, 710, 722, 735, 752, 757, 763, 772, 783, 794, 814, 854, 867, 880, 893, 902, 915, 925, 933, 943, 956, 981, 992, 997, 1019, 1040, 1050, 1080, 1089, 1102, 1110, 1116, 1125, 1134, 1139, 1147, 1176, 1186, 1192, 1199, 1211, 1221, 1228, 1234, 1243, 1257, 1264, 1299, 1304, 1315, 1328, 1333, 1340, 1347, 1384, 1413, 1435, 1443, 1470, 1486, 1540, 1562, 1583, 1627, 1635, 1656, 1661, 1668, 1678, 1687, 1716, 1721, 1726, 1732, 1793, 1798, 1807, 1812, 1823, 1834, 1843, 1855, 1865, 1927, 1932, 1938, 1946, 1956, 1965, 1973, 1991, 2004, 2010, 2015, 2020, 2027, 2035, 2043, 2051, 2060, 2071, 2093, 2098, 2106, 2117, 2122, 2127, 2132, 2137, 2142, 2156, 2172, 2182, 2199, 2216, 2225, 2246, 2253, 2264, 2274, 2281, 2290, 2300, 2305, 2311, 2318, 2327, 2335, 2340, 2351, 2356, 2361, 2366, 2371, 2376, 2381, 2394, 2399, 2406, 2411, 2420, 2425, 2435, 2447, 2456, 2462, 2468, 2477, 2482, 2487, 2493, 2498, 2503, 2515, 2520, 2525, 2530, 2539, 2545, 2553, 2558, 2564, 2573, 2578, 2585, 2590, 2597, 2602, 2609, 2619, 2626, 2636, 2643, 2654, 2670, 2686, 2707, 2712, 2717, 2722, 2727, 2736, 2741, 2748, 2756, 2761, 2766, 2772, 2780, 2791, 2808, 2818, 2831, 2852, 2857, 2862, 2871, 2891, 2899, 2904, 2911, 2930, 2937, 2942, 2947, 2952, 2960, 2970, 2981, 2999, 3009, 3022, 3028, 3048, 3060, 3072, 3082, 3090, 3104, 3109, 3114, 3121, 3129, 3138, 3165, 3197, 3205, 3210]


#[405, 414, 433, 443, 454, 463, 472, 483, 510, 525, 534, 544, 555, 566, 577, 587, 607, 612, 617, 629, 644, 652, 666, 690, 702, 710, 722, 735, 752, 757, 763, 772, 783, 794, 814, 854, 867, 880, 893, 902, 915, 925, 933, 943, 956, 981, 992, 997, 1019, 1040, 1050, 1080, 1089, 1102, 1110, 1116, 1125, 1134, 1139, 1147, 1176, 1186, 1192, 1199, 1211, 1221, 1228, 1234, 1243, 1257, 1264, 1299, 1304, 1315, 1328, 1333, 1340, 1347, 1384, 1413, 1435, 1443, 1470, 1486, 1540, 1562, 1583, 1627, 1635, 1656, 1661, 1668, 1678, 1687, 1716, 1721, 1726, 1732, 1793, 1798, 1807, 1812, 1823, 1834, 1843, 1855, 1865, 1927, 1932, 1938, 1946, 1956, 1965, 1973, 1991, 2004, 2010, 2015, 2020, 2027, 2035, 2043, 2051, 2060, 2071, 2093, 2098, 2106, 2117, 2122, 2127, 2132, 2137, 2142, 2156, 2172, 2182, 2199, 2216, 2225, 2246, 2253, 2264, 2274, 2281, 2290, 2300, 2305, 2311, 2318, 2327, 2335, 2340, 2351, 2356, 2361, 2366, 2371, 2376, 2381, 2394, 2399, 2406, 2411, 2420, 2425, 2435, 2447, 2456, 2462, 2468, 2477, 2482, 2487, 2493, 2498, 2503, 2515, 2520, 2525, 2530, 2539, 2545, 2553, 2558, 2564, 2573, 2578, 2585, 2590, 2597, 2602, 2609, 2619, 2626, 2636, 2643, 2654, 2670, 2686, 2707, 2712, 2717, 2722, 2727, 2736, 2741, 2748, 2756, 2761, 2766, 2772, 2780, 2791, 2808, 2818, 2831, 2852, 2857, 2862, 2871, 2891, 2899, 2904, 2911, 2930, 2937, 2942, 2947, 2952, 2960, 2970, 2981, 2999, 3009, 3022, 3028, 3048, 3060, 3072, 3082, 3090, 3104, 3109, 3114, 3121, 3129, 3138, 3165, 3197, 3205, 3210]



# Camera folder pattern (matches cam0, cam1, cam2, etc.)
CAMERA_FOLDER_PATTERN = re.compile(r'^cam\d+$')

# Common image extensions
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}


def is_camera_folder(folder_name: str) -> bool:
    """Check if a folder name matches the camera folder pattern (cam0, cam1, etc.)"""
    return CAMERA_FOLDER_PATTERN.match(folder_name) is not None


def get_image_files(directory: Path) -> List[Path]:
    """Get all image files in a directory, sorted by name."""
    if not directory.exists():
        return []
    
    image_files = []
    for file_path in directory.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS:
            image_files.append(file_path)
    
    # Sort by filename to ensure consistent ordering
    return sorted(image_files)


def extract_frame_id_from_filename(filename: str) -> Optional[int]:
    """
    Extract frame ID from filename. Assumes filenames contain frame numbers.
    
    Common patterns:
    - frame_000001.jpg -> 1
    - img_0010.png -> 10
    - 000025.jpg -> 25
    - image_frame_050.jpg -> 50
    """
    # Try to find numbers in the filename
    numbers = re.findall(r'\d+', filename)
    if numbers:
        # Usually the last or largest number is the frame ID
        # You might need to adjust this logic based on your naming convention
        return int(numbers[-1])  # Take the last number found
    return None


def copy_image_subset(source_dir: str, dest_dir: str, frame_ids: List[int], 
                     dry_run: bool = False) -> None:
    """
    Copy a subset of images from source to destination directory.
    
    Args:
        source_dir: Source directory path
        dest_dir: Destination directory path  
        frame_ids: List of frame IDs to copy
        dry_run: If True, only print what would be copied without actually copying
    """
    source_path = Path(source_dir)
    dest_path = Path(dest_dir)
    
    if not source_path.exists():
        logger.error(f"Source directory does not exist: {source_path}")
        return
    
    if not source_path.is_dir():
        logger.error(f"Source path is not a directory: {source_path}")
        return
    
    logger.info(f"Source directory: {source_path}")
    logger.info(f"Destination directory: {dest_path}")
    logger.info(f"Frame IDs to copy: {frame_ids}")
    logger.info(f"Dry run: {dry_run}")
    
    # Create destination directory if it doesn't exist
    if not dry_run:
        dest_path.mkdir(parents=True, exist_ok=True)
    
    total_copied = 0
    total_skipped = 0
    
    # Process each subdirectory in source
    for item in source_path.iterdir():
        if not item.is_dir():
            logger.debug(f"Skipping non-directory: {item.name}")
            continue
            
        if not is_camera_folder(item.name):
            logger.info(f"Skipping non-camera folder: {item.name}")
            continue
        
        logger.info(f"Processing camera folder: {item.name}")
        
        # Get all image files in this camera folder
        image_files = get_image_files(item)
        logger.info(f"Found {len(image_files)} images in {item.name}")
        
        if not image_files:
            logger.warning(f"No images found in {item.name}")
            continue
        
        # Create destination camera folder
        dest_camera_dir = dest_path / item.name
        if not dry_run:
            dest_camera_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy images based on frame IDs
        copied_count = 0
        
        # Method 1: Copy by frame ID extracted from filename
        for image_file in image_files:
            frame_id = extract_frame_id_from_filename(image_file.name)
            
            if frame_id is not None and frame_id in frame_ids:
                dest_file = dest_camera_dir / image_file.name
                
                if dry_run:
                    logger.info(f"Would copy: {image_file} -> {dest_file}")
                else:
                    try:
                        shutil.copy2(image_file, dest_file)
                        logger.debug(f"Copied: {image_file.name} (frame {frame_id})")
                        copied_count += 1
                    except Exception as e:
                        logger.error(f"Failed to copy {image_file}: {e}")
            else:
                total_skipped += 1
        
        logger.info(f"Copied {copied_count} images from {item.name}")
        total_copied += copied_count
    
    logger.info(f"Summary: {total_copied} images copied, {total_skipped} images skipped")
    
    if dry_run:
        logger.info("This was a dry run. No files were actually copied.")


def main():
    """Main function with command line argument parsing."""
    parser = argparse.ArgumentParser(
        description="Copy a subset of images from camera subfolders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Examples:
    # Copy specific frame IDs
    python copy_image_subset.py --image_path ./data/calib --dest_path ./data/calib_subset --frames 0,10,20,30
    
    # Dry run to see what would be copied
    python copy_image_subset.py --image_path ./data/calib --dest_path ./data/calib_subset --frames 0,5,10 --dry_run
    
    # Use default settings (modify DEFAULT_* constants in script)
    python copy_image_subset.py
        """
    )
    
    parser.add_argument(
        '--image_path', '-s',
        type=str,
        default=DEFAULT_SOURCE_DIR,
        help=f'Source directory path (default: {DEFAULT_SOURCE_DIR})'
    )
    
    parser.add_argument(
        '--dest_path', '-d', 
        type=str,
        default=DEFAULT_DEST_DIR,
        help=f'Destination directory path (default: {DEFAULT_DEST_DIR})'
    )
    
    parser.add_argument(
        '--frames', '-f',
        type=str,
        default=','.join(map(str, DEFAULT_FRAME_IDS)),
        help=f'Comma-separated list of frame IDs to copy (default: {",".join(map(str, DEFAULT_FRAME_IDS))})'
    )
    
    parser.add_argument(
        '--dry_run',
        action='store_true',
        help='Show what would be copied without actually copying files'
    )
    
    
    args = parser.parse_args()
    
    
    # Parse frame IDs
    try:
        frame_ids = [int(x.strip()) for x in args.frames.split(',') if x.strip()]
    except ValueError as e:
        logger.error(f"Invalid frame IDs format: {e}")
        return
    
    if not frame_ids:
        logger.error("No valid frame IDs provided")
        return
    
    # Perform the copy operation
    copy_image_subset(args.image_path, args.dest_path, frame_ids, args.dry_run)


if __name__ == '__main__':
    main()
