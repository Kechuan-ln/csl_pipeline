import os
import argparse
import cv2
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from tqdm import tqdm
import json

# This script compares images in two directories and generates a report with statistics and visualizations.


def get_all_image_paths(directory):
    """Get all image file paths recursively from a directory."""
    image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'}
    image_paths = []
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if Path(file).suffix.lower() in image_extensions:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, directory)
                image_paths.append(rel_path)
    
    return sorted(image_paths)


def compare_images(img1_path, img2_path, threshold=1e-6):
    """
    Compare two images and return difference statistics.
    
    Args:
        img1_path: Path to first image
        img2_path: Path to second image  
        threshold: Threshold for considering pixels as different
        
    Returns:
        dict: Comparison results including metrics and difference image
    """
    try:
        img1 = cv2.imread(img1_path)
        img2 = cv2.imread(img2_path)
        
        if img1 is None or img2 is None:
            return {
                'status': 'error',
                'error': f'Failed to load images: {img1_path}, {img2_path}',
                'identical': False
            }
        
        # Check if images have same dimensions
        if img1.shape != img2.shape:
            return {
                'status': 'different_dimensions',
                'img1_shape': img1.shape,
                'img2_shape': img2.shape,
                'identical': False
            }
        
        # Convert to float for accurate comparison
        img1_float = img1.astype(np.float32)
        img2_float = img2.astype(np.float32)
        
        # Calculate absolute difference
        diff = np.abs(img1_float - img2_float)
        
        # Check if images are identical
        max_diff = np.max(diff)
        mean_diff = np.mean(diff)
        
        # Calculate percentage of different pixels
        different_pixels = np.sum(diff > threshold)
        total_pixels = diff.size
        diff_percentage = (different_pixels / total_pixels) * 100
        
        # Create difference visualization
        diff_vis = np.clip(diff * 10, 0, 255).astype(np.uint8)  # Amplify differences
        
        # Calculate structural similarity metrics
        mse = np.mean((img1_float - img2_float) ** 2)
        
        if mse == 0:
            psnr = float('inf')
        else:
            psnr = 20 * np.log10(255.0 / np.sqrt(mse))
        
        return {
            'status': 'success',
            'identical': max_diff < threshold,
            'max_difference': float(max_diff),
            'mean_difference': float(mean_diff),
            'mse': float(mse),
            'psnr': float(psnr),
            'different_pixels': int(different_pixels),
            'total_pixels': int(total_pixels),
            'diff_percentage': float(diff_percentage),
            'difference_image': diff_vis
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'identical': False
        }


def visualize_differences(img1_path, img2_path, diff_result, output_path):
    """Create a visualization showing original images and their difference."""
    if diff_result['status'] != 'success':
        return
    
    try:
        img1 = cv2.imread(img1_path)
        img2 = cv2.imread(img2_path)
        
        # Convert BGR to RGB for matplotlib
        img1_rgb = cv2.cvtColor(img1, cv2.COLOR_BGR2RGB)
        img2_rgb = cv2.cvtColor(img2, cv2.COLOR_BGR2RGB)
        diff_vis = diff_result['difference_image']
        
        # Create figure with subplots
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        
        # Original images
        axes[0, 0].imshow(img1_rgb)
        axes[0, 0].set_title('Directory 1')
        axes[0, 0].axis('off')
        
        axes[0, 1].imshow(img2_rgb)
        axes[0, 1].set_title('Directory 2')
        axes[0, 1].axis('off')
        
        # Difference visualization
        axes[1, 0].imshow(diff_vis)
        axes[1, 0].set_title('Difference (amplified)')
        axes[1, 0].axis('off')
        
        # Statistics text
        stats_text = f"""Comparison Statistics:
Max Difference: {diff_result['max_difference']:.2f}
Mean Difference: {diff_result['mean_difference']:.2f}
MSE: {diff_result['mse']:.2f}
PSNR: {diff_result['psnr']:.2f} dB
Different Pixels: {diff_result['diff_percentage']:.2f}%
Identical: {diff_result['identical']}"""
        
        axes[1, 1].text(0.1, 0.5, stats_text, fontsize=10, verticalalignment='center')
        axes[1, 1].axis('off')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
    except Exception as e:
        print(f"Error creating visualization: {e}")


def compare_directories(dir1, dir2, output_dir, threshold=1e-6, create_visualizations=True):
    """
    Compare all images in two directories with the same relative paths.
    
    Args:
        dir1: First directory path
        dir2: Second directory path
        output_dir: Directory to save comparison results
        threshold: Pixel difference threshold
        create_visualizations: Whether to create difference visualizations
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Get all image paths from both directories
    images1 = set(get_all_image_paths(dir1))
    images2 = set(get_all_image_paths(dir2))
    
    # Find common and unique images
    common_images = images1.intersection(images2)
    only_in_dir1 = images1 - images2
    only_in_dir2 = images2 - images1
    
    print(f"Found {len(images1)} images in directory 1")
    print(f"Found {len(images2)} images in directory 2")
    print(f"Common images: {len(common_images)}")
    print(f"Only in directory 1: {len(only_in_dir1)}")
    print(f"Only in directory 2: {len(only_in_dir2)}")
    
    # Results storage
    comparison_results = {
        'directory1': str(dir1),
        'directory2': str(dir2),
        'threshold': threshold,
        'summary': {
            'total_images_dir1': len(images1),
            'total_images_dir2': len(images2),
            'common_images': len(common_images),
            'only_in_dir1': len(only_in_dir1),
            'only_in_dir2': len(only_in_dir2),
            'identical_images': 0,
            'different_images': 0,
            'error_images': 0
        },
        'image_results': {},
        'missing_files': {
            'only_in_dir1': list(only_in_dir1),
            'only_in_dir2': list(only_in_dir2)
        }
    }
    
    if create_visualizations:
        vis_dir = os.path.join(output_dir, 'visualizations')
        os.makedirs(vis_dir, exist_ok=True)
    
    # Compare common images
    print("Comparing common images...")
    for rel_path in tqdm(common_images):
        img1_path = os.path.join(dir1, rel_path)
        img2_path = os.path.join(dir2, rel_path)
        
        # Compare images
        result = compare_images(img1_path, img2_path, threshold)
        comparison_results['image_results'][rel_path] = result
        
        # Update summary statistics
        if result['status'] == 'success':
            if result['identical']:
                comparison_results['summary']['identical_images'] += 1
            else:
                comparison_results['summary']['different_images'] += 1
        else:
            comparison_results['summary']['error_images'] += 1
        
        # Create visualization for different images
        if create_visualizations and result['status'] == 'success' and not result['identical']:
            vis_filename = rel_path.replace('/', '_').replace('\\', '_') + '_comparison.png'
            vis_path = os.path.join(vis_dir, vis_filename)
            visualize_differences(img1_path, img2_path, result, vis_path)
    
    # Save results to JSON
    results_path = os.path.join(output_dir, 'comparison_results.json')
    with open(results_path, 'w') as f:
        # Remove difference_image from results for JSON serialization
        json_results = comparison_results.copy()
        for img_path, result in json_results['image_results'].items():
            if 'difference_image' in result:
                del result['difference_image']
        json.dump(json_results, f, indent=2)
    
    # Print summary
    print(f"\nComparison Summary:")
    print(f"Identical images: {comparison_results['summary']['identical_images']}")
    print(f"Different images: {comparison_results['summary']['different_images']}")
    print(f"Error images: {comparison_results['summary']['error_images']}")
    print(f"Results saved to: {results_path}")
    
    if create_visualizations and comparison_results['summary']['different_images'] > 0:
        print(f"Visualizations saved to: {vis_dir}")
    
    return comparison_results


def main():
    parser = argparse.ArgumentParser(description='Compare images in two directories')
    parser.add_argument('--dir1', required=True, help='First directory to compare')
    parser.add_argument('--dir2', required=True, help='Second directory to compare')
    parser.add_argument('--output_dir', required=True, help='Output directory for results')
    parser.add_argument('--threshold', type=float, default=1e-6,
                       help='Pixel difference threshold for considering images identical')
    parser.add_argument('--no_visualizations', action='store_true',
                       help='Skip creating difference visualizations')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.dir1):
        print(f"Error: Directory 1 does not exist: {args.dir1}")
        return
    
    if not os.path.exists(args.dir2):
        print(f"Error: Directory 2 does not exist: {args.dir2}")
        return
    
    create_vis = not args.no_visualizations
    
    compare_directories(
        args.dir1, 
        args.dir2, 
        args.output_dir, 
        args.threshold, 
        create_vis
    )


if __name__ == '__main__':
    main()