import os
import argparse
import glob

import sys
sys.path.append('..')  # Adjust path to include parent directory

import shutil
import subprocess
from utils.constants import PATH_ASSETS_VIDEOS, IMG_FORMAT_IO


def synchronize_videos(list_src_videos, out_dir, use_fast_copy, duration, offset):
    list_output_videos=[]
    
    for i, path_video in enumerate(list_src_videos):
        video_tag = '/'.join(path_video.split('/')[-2:])

        path_output = os.path.join(out_dir, video_tag)
        if not os.path.exists(os.path.dirname(path_output)):
            os.makedirs(os.path.dirname(path_output))
        list_output_videos.append(path_output)
        
        
        # The video starts earlier than our sync point, so we'll trim the beginning
        cmd = ["ffmpeg", "-i", path_video, "-ss", str(offset), "-t", str(duration), "-c:v", "copy" if use_fast_copy else "libx264", "-c:a", "copy", "-y", path_output]
        subprocess.run(cmd)

    return list_output_videos


def parse_args():    
    parser = argparse.ArgumentParser(description="Convert MP4 videos to images")
    parser.add_argument("--src_tag", default='intr_09121',  help="Source directory containing camera folders, under PATH_ASSETS_VIDEOS")
    parser.add_argument("--out_tag", default='intr_09121_trimmed', help="Output directory to save trimmed videos, under PATH_ASSETS_VIDEOS")
    parser.add_argument("--duration", type=float, default=10, help="Duration in seconds to extract from the video (optional)")
    parser.add_argument("--ss", type=float, default=0, help="Offset to start extracting from the video (optional)")
    parser.add_argument('--fast_copy', action='store_true', help='fast copy without re-encoding')
    
    args = parser.parse_args()
    return args


def main():
    args = parse_args()

    root_dir = PATH_ASSETS_VIDEOS
    src_dir = os.path.join(root_dir, args.src_tag)
    out_dir = os.path.join(root_dir, args.out_tag)
    os.makedirs(out_dir, exist_ok=True)

    list_src_videos=glob.glob(os.path.join(src_dir,'*/*.MP4'))
    list_src_videos.sort()
    print("list_src_videos:",list_src_videos)

    synchronize_videos(list_src_videos,out_dir, args.fast_copy, args.duration, args.ss)

if __name__ == "__main__":
    main()
