#!/usr/bin/env python3

import json
import numpy as np
import argparse
import os
import sys

from fov_to_intrinsics import focal_length_to_fov, calculate_diagonal_fov

def load_intrinsics_json(file_path):
    """Load intrinsics from JSON file."""
    with open(file_path, 'r') as f:
        return json.load(f)

def extract_camera_parameters(camera_data):
    """Extract K matrix and image size from camera data."""
    K = np.array(camera_data['K'], dtype=np.float64)
    image_size = camera_data['image_size']
    
    fx = K[0, 0]
    fy = K[1, 1]
    cx = K[0, 2] 
    cy = K[1, 2]
    
    width, height = image_size
    
    return fx, fy, cx, cy, width, height

def compute_fov_from_intrinsics(fx, fy, width, height):
    """Compute FOV angles from intrinsic parameters."""
    fov_horizontal = focal_length_to_fov(fx, width)
    fov_vertical = focal_length_to_fov(fy, height)
    fov_diagonal = calculate_diagonal_fov(fov_horizontal, fov_vertical)
    
    return fov_horizontal, fov_vertical, fov_diagonal

def print_camera_fov_info(camera_name, fx, fy, cx, cy, width, height, 
                         fov_h, fov_v, fov_d):
    """Print detailed FOV information for a camera."""

    print(f"Camera: {camera_name}")
    print(f"  Image size: {width} x {height}")
    print(f"  Focal lengths: fx = {fx:.2f}, fy = {fy:.2f}")
    print(f"  Principal point: cx = {cx:.2f}, cy = {cy:.2f}")
    print(f"  Field of View:")
    print(f"    Horizontal: {fov_h:.2f}°")
    print(f"    Vertical: {fov_v:.2f}°")
    print(f"    Diagonal: {fov_d:.2f}°")
    print("-" * 50)

def analyze_intrinsics_file(intrinsics_path, output_file=None):
    """Analyze intrinsics file and compute FOV for all cameras."""
    
    if not os.path.exists(intrinsics_path):
        print(f"File {intrinsics_path} does not exist")
        return None
    
    print(f"Loading intrinsics from: {intrinsics_path}")
    intrinsics_data = load_intrinsics_json(intrinsics_path)
    
    if 'cameras' not in intrinsics_data:
        print("No 'cameras' section found in intrinsics file")
        return None
    
    cameras = intrinsics_data['cameras']
    results = {}
    
    print(f"Found {len(cameras)} cameras: {list(cameras.keys())}")
    print("=" * 80)
    
    for camera_name, camera_data in cameras.items():
        try:
            # Extract camera parameters
            fx, fy, cx, cy, width, height = extract_camera_parameters(camera_data)
            
            # Compute FOV
            fov_h, fov_v, fov_d = compute_fov_from_intrinsics(fx, fy, width, height)
            
            # Store results
            results[camera_name] = {
                'image_size': [width, height],
                'focal_lengths': [fx, fy],
                'principal_point': [cx, cy],
                'field_of_view': {
                    'horizontal_degrees': fov_h,
                    'vertical_degrees': fov_v,
                    'diagonal_degrees': fov_d
                }
            }
            
            # Print information
            print_camera_fov_info(camera_name, fx, fy, cx, cy, width, height, 
                                fov_h, fov_v, fov_d)
            
        except Exception as e:
            print(f"Error processing camera {camera_name}: {e}")
            continue
    
    # Summary statistics
    if results:
        fov_h_values = [results[cam]['field_of_view']['horizontal_degrees'] for cam in results]
        fov_v_values = [results[cam]['field_of_view']['vertical_degrees'] for cam in results]
        fov_d_values = [results[cam]['field_of_view']['diagonal_degrees'] for cam in results]
        
        print("Summary Statistics:")
        print(f"  Horizontal FOV: {np.mean(fov_h_values):.2f}° ± {np.std(fov_h_values):.2f}°")
        print(f"  Vertical FOV: {np.mean(fov_v_values):.2f}° ± {np.std(fov_v_values):.2f}°")
        print(f"  Diagonal FOV: {np.mean(fov_d_values):.2f}° ± {np.std(fov_d_values):.2f}°")
        
        print(f"  FOV Range - Horizontal: [{np.min(fov_h_values):.2f}°, {np.max(fov_h_values):.2f}°]")
        print(f"  FOV Range - Vertical: [{np.min(fov_v_values):.2f}°, {np.max(fov_v_values):.2f}°]")
        print(f"  FOV Range - Diagonal: [{np.min(fov_d_values):.2f}°, {np.max(fov_d_values):.2f}°]")
    
    # Save results if requested
    if output_file and results:
        output_data = {
            'source_file': intrinsics_path,
            'cameras': results,
            'summary': {
                'num_cameras': len(results),
                'average_horizontal_fov': np.mean(fov_h_values),
                'average_vertical_fov': np.mean(fov_v_values),
                'average_diagonal_fov': np.mean(fov_d_values),
                'horizontal_fov_std': np.std(fov_h_values),
                'vertical_fov_std': np.std(fov_v_values),
                'diagonal_fov_std': np.std(fov_d_values)
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"Results saved to: {output_file}")
    
    return results

def main():
    parser = argparse.ArgumentParser(
        description="Compute field of view (FOV) from camera intrinsics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        Examples:
        # Analyze default intrinsics file
        python tool_scripts/intrinsics_to_fov.py
        
        # Analyze specific intrinsics file
        python tool_scripts/intrinsics_to_fov.py --input assets/videos/extr_623_sync2/calibration.json
        
        # Analyze and save results
        python tool_scripts/intrinsics_to_fov.py --input intrinsic.json --output fov_analysis.json
        """
    )
    
    parser.add_argument('--input', '-i', default='intrinsic.json',
                       help='Path to intrinsics JSON file (default: intrinsic.json)')
    parser.add_argument('--output', '-o',
                       help='Output JSON file for results (optional)')
    
    args = parser.parse_args()
    
    results = analyze_intrinsics_file(args.input, args.output)
        

if __name__ == "__main__":
    exit(main())