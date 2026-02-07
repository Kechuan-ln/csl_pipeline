#!/usr/bin/env python3
"""
FOV to Camera Intrinsics Calculator

This module provides functions to calculate camera intrinsic parameters from
field of view (FOV) angles and image dimensions.

Author: Assistant
Date: 2025-06-30
"""

import numpy as np
import math
import argparse
import json
from typing import Tuple, Optional, Dict, Any


def degrees_to_radians(degrees: float) -> float:
    """Convert degrees to radians."""
    return degrees * math.pi / 180.0


def radians_to_degrees(radians: float) -> float:
    """Convert radians to degrees."""
    return radians * 180.0 / math.pi


def fov_to_focal_length(fov_degrees: float, image_dimension: int) -> float:
    """
    Calculate focal length from field of view and image dimension.
    
    Args:
        fov_degrees: Field of view in degrees
        image_dimension: Image dimension (width or height) in pixels
    
    Returns:
        Focal length in pixels
    """
    if fov_degrees <= 0 or fov_degrees >= 180:
        raise ValueError(f"FOV must be between 0 and 180 degrees, got {fov_degrees}")
    
    fov_radians = degrees_to_radians(fov_degrees)
    focal_length = image_dimension / (2.0 * math.tan(fov_radians / 2.0))
    return focal_length


def focal_length_to_fov(focal_length: float, image_dimension: int) -> float:
    """
    Calculate field of view from focal length and image dimension.
    
    Args:
        focal_length: Focal length in pixels
        image_dimension: Image dimension (width or height) in pixels
    
    Returns:
        Field of view in degrees
    """
    if focal_length <= 0:
        raise ValueError(f"Focal length must be positive, got {focal_length}")
    
    fov_radians = 2.0 * math.atan(image_dimension / (2.0 * focal_length))
    return radians_to_degrees(fov_radians)


def calculate_diagonal_fov(fov_horizontal: float, fov_vertical: float) -> float:
    """
    Calculate diagonal FOV from horizontal and vertical FOV.
    
    Args:
        fov_horizontal: Horizontal FOV in degrees
        fov_vertical: Vertical FOV in degrees
    
    Returns:
        Diagonal FOV in degrees
    """
    # Convert to half-angles in radians
    half_h = degrees_to_radians(fov_horizontal) / 2.0
    half_v = degrees_to_radians(fov_vertical) / 2.0
    
    # Calculate diagonal half-angle
    half_d = math.atan(math.sqrt(math.tan(half_h)**2 + math.tan(half_v)**2))
    
    # Convert back to full angle in degrees
    return radians_to_degrees(2.0 * half_d)


def calculate_fov_from_diagonal(fov_diagonal: float, aspect_ratio: float) -> Tuple[float, float]:
    """
    Calculate horizontal and vertical FOV from diagonal FOV and aspect ratio.
    
    Args:
        fov_diagonal: Diagonal FOV in degrees
        aspect_ratio: Width/height ratio
    
    Returns:
        Tuple of (horizontal_fov, vertical_fov) in degrees
    """
    # Convert diagonal half-angle to radians
    half_d = degrees_to_radians(fov_diagonal) / 2.0
    
    # Calculate horizontal and vertical half-angles
    # Using the relationship: tan(half_d) = sqrt(tan(half_h)^2 + tan(half_v)^2)
    # And: tan(half_h) / tan(half_v) = aspect_ratio
    
    tan_half_d = math.tan(half_d)
    tan_half_v = tan_half_d / math.sqrt(1 + aspect_ratio**2)
    tan_half_h = aspect_ratio * tan_half_v
    
    half_h = math.atan(tan_half_h)
    half_v = math.atan(tan_half_v)
    
    fov_horizontal = radians_to_degrees(2.0 * half_h)
    fov_vertical = radians_to_degrees(2.0 * half_v)
    
    return fov_horizontal, fov_vertical


def validate_fov_consistency(fov_horizontal: Optional[float], 
                           fov_vertical: Optional[float], 
                           fov_diagonal: Optional[float],
                           tolerance: float = 1.0) -> bool:
    """
    Validate that provided FOV values are consistent with each other.
    
    Args:
        fov_horizontal: Horizontal FOV in degrees (optional)
        fov_vertical: Vertical FOV in degrees (optional)
        fov_diagonal: Diagonal FOV in degrees (optional)
        tolerance: Tolerance for consistency check in degrees
    
    Returns:
        True if consistent, False otherwise
    """
    if fov_horizontal is not None and fov_vertical is not None and fov_diagonal is not None:
        calculated_diagonal = calculate_diagonal_fov(fov_horizontal, fov_vertical)
        print('Calculated diagonal FOV:', calculated_diagonal, 'Expected diagonal FOV:', fov_diagonal)
        return abs(calculated_diagonal - fov_diagonal) <= tolerance
    
    return True  # If not all three are provided, we can't check consistency


def fov_to_intrinsics(image_width: int,
                     image_height: int,
                     fov_horizontal: Optional[float] = None,
                     fov_vertical: Optional[float] = None,
                     fov_diagonal: Optional[float] = None,
                     principal_point: Optional[Tuple[float, float]] = None) -> np.ndarray:
    """
    Calculate camera intrinsic matrix from FOV angles and image dimensions.
    
    Args:
        image_width: Image width in pixels
        image_height: Image height in pixels
        fov_horizontal: Horizontal FOV in degrees (optional)
        fov_vertical: Vertical FOV in degrees (optional)
        fov_diagonal: Diagonal FOV in degrees (optional)
        principal_point: (cx, cy) principal point coordinates (optional, defaults to image center)
    
    Returns:
        3x3 camera intrinsic matrix
    
    Raises:
        ValueError: If insufficient or inconsistent FOV information is provided
    """
    # Validate inputs
    if image_width <= 0 or image_height <= 0:
        raise ValueError("Image dimensions must be positive")
    
    # Count how many FOV values are provided
    fov_count = sum(x is not None for x in [fov_horizontal, fov_vertical, fov_diagonal])
    
    if fov_count == 0:
        raise ValueError("At least one FOV value must be provided")
    
    # Validate FOV consistency if multiple values provided
    print('fov_horizontal:', fov_horizontal,' fov_vertical:', fov_vertical, 'fov_diagonal:', fov_diagonal)
    if not validate_fov_consistency(fov_horizontal, fov_vertical, fov_diagonal):
        raise ValueError("Provided FOV values are inconsistent")
    
    # Calculate missing FOV values
    aspect_ratio = image_width / image_height
    
    if fov_horizontal is None or fov_vertical is None:
        if fov_diagonal is not None:
            if fov_horizontal is None and fov_vertical is None:
                fov_horizontal, fov_vertical = calculate_fov_from_diagonal(fov_diagonal, aspect_ratio)
            elif fov_horizontal is None:
                # Calculate horizontal from vertical and diagonal
                half_v = degrees_to_radians(fov_vertical) / 2.0
                half_d = degrees_to_radians(fov_diagonal) / 2.0
                tan_half_d = math.tan(half_d)
                tan_half_v = math.tan(half_v)
                tan_half_h = math.sqrt(tan_half_d**2 - tan_half_v**2)
                fov_horizontal = radians_to_degrees(2.0 * math.atan(tan_half_h))
            else:  # fov_vertical is None
                # Calculate vertical from horizontal and diagonal
                half_h = degrees_to_radians(fov_horizontal) / 2.0
                half_d = degrees_to_radians(fov_diagonal) / 2.0
                tan_half_d = math.tan(half_d)
                tan_half_h = math.tan(half_h)
                tan_half_v = math.sqrt(tan_half_d**2 - tan_half_h**2)
                fov_vertical = radians_to_degrees(2.0 * math.atan(tan_half_v))
        else:
            # Only one of horizontal or vertical is provided
            if fov_horizontal is not None:
                # Assume square pixels, calculate vertical from aspect ratio
                fx = fov_to_focal_length(fov_horizontal, image_width)
                fov_vertical = focal_length_to_fov(fx, image_height)
            else:  # fov_vertical is not None
                # Assume square pixels, calculate horizontal from aspect ratio
                fy = fov_to_focal_length(fov_vertical, image_height)
                fov_horizontal = focal_length_to_fov(fy, image_width)
    
    # Calculate focal lengths
    fx = fov_to_focal_length(fov_horizontal, image_width)
    fy = fov_to_focal_length(fov_vertical, image_height)
    
    # Set principal point (default to image center)
    if principal_point is None:
        cx = image_width / 2.0
        cy = image_height / 2.0
    else:
        cx, cy = principal_point
    
    # Construct intrinsic matrix
    intrinsic_matrix = np.array([
        [fx,  0, cx],
        [ 0, fy, cy],
        [ 0,  0,  1]
    ], dtype=np.float64)
    
    return intrinsic_matrix


def print_intrinsics_info(intrinsic_matrix: np.ndarray, 
                         image_width: int, 
                         image_height: int) -> None:
    """
    Print detailed information about the camera intrinsics.
    
    Args:
        intrinsic_matrix: 3x3 camera intrinsic matrix
        image_width: Image width in pixels
        image_height: Image height in pixels
    """
    fx, fy = intrinsic_matrix[0, 0], intrinsic_matrix[1, 1]
    cx, cy = intrinsic_matrix[0, 2], intrinsic_matrix[1, 2]
    
    # Calculate FOV values for verification
    fov_h = focal_length_to_fov(fx, image_width)
    fov_v = focal_length_to_fov(fy, image_height)
    fov_d = calculate_diagonal_fov(fov_h, fov_v)
    
    print("Camera Intrinsic Parameters:")
    print("=" * 40)
    print(f"Image size: {image_width} x {image_height}")
    print(f"Focal lengths: fx = {fx:.2f}, fy = {fy:.2f}")
    print(f"Principal point: cx = {cx:.2f}, cy = {cy:.2f}")
    print(f"Aspect ratio: {image_width/image_height:.3f}")
    print()
    print("Field of View:")
    print(f"Horizontal: {fov_h:.2f}°")
    print(f"Vertical: {fov_v:.2f}°")
    print(f"Diagonal: {fov_d:.2f}°")
    print()
    print("Intrinsic Matrix:")
    print(intrinsic_matrix)
    print()
    print("Intrinsic Matrix (OpenCV format):")
    print(f"K = [[{fx:.6f}, 0.000000, {cx:.6f}],")
    print(f"     [0.000000, {fy:.6f}, {cy:.6f}],")
    print(f"     [0.000000, 0.000000, 1.000000]]")


def save_intrinsics_json(intrinsic_matrix: np.ndarray, 
                        image_width: int, 
                        image_height: int,
                        filename: str) -> None:
    """
    Save camera intrinsics to JSON file.
    
    Args:
        intrinsic_matrix: 3x3 camera intrinsic matrix
        image_width: Image width in pixels
        image_height: Image height in pixels
        filename: Output JSON filename
    """
    fx, fy = intrinsic_matrix[0, 0], intrinsic_matrix[1, 1]
    cx, cy = intrinsic_matrix[0, 2], intrinsic_matrix[1, 2]
    
    # Calculate FOV values
    fov_h = focal_length_to_fov(fx, image_width)
    fov_v = focal_length_to_fov(fy, image_height)
    fov_d = calculate_diagonal_fov(fov_h, fov_v)
    
    data = {
        "image_size": [image_width, image_height],
        "intrinsic_matrix": intrinsic_matrix.tolist(),
        "focal_lengths": [fx, fy],
        "principal_point": [cx, cy],
        "field_of_view": {
            "horizontal_degrees": fov_h,
            "vertical_degrees": fov_v,
            "diagonal_degrees": fov_d
        },
        "opencv_format": {
            "K": intrinsic_matrix.flatten().tolist(),
            "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0]  # Assuming no distortion
        }
    }
    
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Intrinsics saved to {filename}")


def main():
    """Command-line interface for the FOV to intrinsics calculator."""
    parser = argparse.ArgumentParser(
        description="Calculate camera intrinsic parameters from field of view angles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using horizontal and vertical FOV
  python fov_to_intrinsics.py --width 1920 --height 1080 --fov-h 90 --fov-v 60
  
  # Using diagonal FOV
  python fov_to_intrinsics.py --width 1920 --height 1080 --fov-d 100
  
  # Using horizontal FOV only (assumes square pixels)
  python fov_to_intrinsics.py --width 1920 --height 1080 --fov-h 90
  
  # Save to JSON file
  python fov_to_intrinsics.py --width 1920 --height 1080 --fov-h 90 --fov-v 60 --output camera_intrinsics.json
        """
    )
    
    parser.add_argument('--width', type=int, required=True,
                       help='Image width in pixels')
    parser.add_argument('--height', type=int, required=True,
                       help='Image height in pixels')
    parser.add_argument('--fov-h', type=float,
                       help='Horizontal field of view in degrees')
    parser.add_argument('--fov-v', type=float,
                       help='Vertical field of view in degrees')
    parser.add_argument('--fov-d', type=float,
                       help='Diagonal field of view in degrees')
    parser.add_argument('--cx', type=float,
                       help='Principal point x-coordinate (default: image center)')
    parser.add_argument('--cy', type=float,
                       help='Principal point y-coordinate (default: image center)')
    parser.add_argument('--output', type=str,
                       help='Output JSON filename (optional)')
    
    args = parser.parse_args()
    
    try:
        # Set principal point if provided
        principal_point = None
        if args.cx is not None and args.cy is not None:
            principal_point = (args.cx, args.cy)
        elif args.cx is not None or args.cy is not None:
            parser.error("Both --cx and --cy must be provided together")
        
        # Calculate intrinsics
        intrinsic_matrix = fov_to_intrinsics(
            image_width=args.width,
            image_height=args.height,
            fov_horizontal=args.fov_h,
            fov_vertical=args.fov_v,
            fov_diagonal=args.fov_d,
            principal_point=principal_point
        )
        
        # Print results
        print_intrinsics_info(intrinsic_matrix, args.width, args.height)
        
        # Save to JSON if requested
        if args.output:
            save_intrinsics_json(intrinsic_matrix, args.width, args.height, args.output)
    
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
