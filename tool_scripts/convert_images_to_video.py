import os
import argparse
import glob
import cv2
from tqdm import tqdm


def convert_images_to_video(image_folder, output_video_path, fps=30, codec='mp4v'):
    """
    Convert a folder of images to a video file.
    
    Args:
        image_folder: Path to folder containing images
        output_video_path: Path for output video file
        fps: Frames per second for output video
        codec: Video codec to use
    """
    # Get all image files and sort by name
    image_extensions = ['*.png', '*.jpg', '*.jpeg', '*.bmp', '*.tiff', '*.tif']
    image_files = []
    
    for ext in image_extensions:
        image_files.extend(glob.glob(os.path.join(image_folder, ext)))
        image_files.extend(glob.glob(os.path.join(image_folder, ext.upper())))
    
    if not image_files:
        print(f"No image files found in {image_folder}")
        return
    
    # Sort files by name
    image_files.sort()
    
    print(f"Found {len(image_files)} images")
    
    # Read first image to get dimensions
    first_image = cv2.imread(image_files[0])
    if first_image is None:
        print(f"Error: Could not read first image {image_files[0]}")
        return
    
    height, width, channels = first_image.shape
    
    # Initialize video writer
    fourcc = cv2.VideoWriter_fourcc(*codec)
    video_writer = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
    
    if not video_writer.isOpened():
        print(f"Error: Could not open video writer for {output_video_path}")
        return
    
    print(f"Creating video: {output_video_path}")
    print(f"Resolution: {width}x{height}")
    print(f"FPS: {fps}")
    print(f"Codec: {codec}")
    
    # Process all images
    for image_path in tqdm(image_files, desc="Processing images"):
        image = cv2.imread(image_path)
        
        if image is None:
            print(f"Warning: Could not read image {image_path}, skipping")
            continue
            
        # Ensure image dimensions match
        if image.shape[:2] != (height, width):
            image = cv2.resize(image, (width, height))
        
        video_writer.write(image)
    
    # Release video writer
    video_writer.release()
    print(f"Video created successfully: {output_video_path}")


def main():
    parser = argparse.ArgumentParser(description="Convert folder of images to video")
    parser.add_argument("--image_folder", help="Path to folder containing images")
    parser.add_argument("--output", "-o", help="Output video path (default: video.mp4 in image folder)")
    parser.add_argument("--fps", type=float, default=30, help="Frames per second (default: 30)")
    parser.add_argument("--codec", default="mp4v", help="Video codec (default: mp4v)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.image_folder):
        print(f"Error: Image folder {args.image_folder} does not exist")
        return
    
    if not os.path.isdir(args.image_folder):
        print(f"Error: {args.image_folder} is not a directory")
        return
    
    # Set default output path if not provided
    if args.output is None:
        args.output = os.path.join(args.image_folder, "video.mp4")
    
    convert_images_to_video(args.image_folder, args.output, args.fps, args.codec)


if __name__ == "__main__":
    main()