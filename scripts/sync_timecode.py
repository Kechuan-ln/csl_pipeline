import os
import subprocess
import argparse
import glob
import json
import sys
sys.path.append('../')
from utils.calib_utils import synchronize_cameras
from utils.constants import PATH_ASSETS_VIDEOS
    


def synchronize_videos(list_src_videos, out_dir, use_fast_copy, path_exist_timecodes=None):
    list_output_videos=[]
    if path_exist_timecodes is not None:
        with open(path_exist_timecodes, 'r') as f:
            meta_info = json.load(f)
    else:
        meta_info = synchronize_cameras(list_src_videos)

    print(meta_info)
    
    for i, path_video in enumerate(list_src_videos):
        video_tag = '/'.join(path_video.split('/')[-2:])
        cmeta = meta_info[video_tag]
        offset = cmeta['offset']
        duration = cmeta['duration']

        path_output = os.path.join(out_dir, video_tag)
        if not os.path.exists(os.path.dirname(path_output)):
            os.makedirs(os.path.dirname(path_output))
        list_output_videos.append(path_output)
        
        
        # The video starts earlier than our sync point, so we'll trim the beginning
        cmd = ["ffmpeg", "-i", path_video, "-ss", str(offset), "-t", str(duration), "-c:v", "copy" if use_fast_copy else "libx264", "-c:a", "copy", "-y", path_output]
        subprocess.run(cmd)

    return meta_info, list_output_videos



def parse_args():
    parser = argparse.ArgumentParser(description='Synchronize GoPro videos using timecodes.')
    parser.add_argument('--src_tag', type=str, default= 'ori', help='subdir containing videos from multiple cameras')
    parser.add_argument('--out_tag', type=str, default= 'sync',help='subdir to save results')
    parser.add_argument('--fast_copy', action='store_true', help='fast copy without re-encoding')
    parser.add_argument('--use_exist_timecodes', action='store_true', help='use existing timecode files if available')

    args = parser.parse_args()
    return args

if __name__ == '__main__':
    args = parse_args()
    root_dir = PATH_ASSETS_VIDEOS
    src_dir = os.path.join(root_dir, args.src_tag)
    out_dir = os.path.join(root_dir, args.out_tag)
    os.makedirs(out_dir, exist_ok=True)

    list_src_videos=glob.glob(os.path.join(src_dir,'*/*.MP4'))
    list_src_videos.sort()
    print("list_src_videos:",list_src_videos)

    if args.use_exist_timecodes:
        path_exist_timecodes = os.path.join(src_dir, 'qr_sync_meta.json')
        assert os.path.exists(path_exist_timecodes), f"Existing timecode file not found: {path_exist_timecodes}"
        print(f"Using Anchor-QR aligned timecode: {path_exist_timecodes}")
    else:
        path_exist_timecodes = None
        print("Using MP4 meta timecode.")

    meta_cam_info, list_output_videos = synchronize_videos(list_src_videos,out_dir, args.fast_copy, path_exist_timecodes)
    meta_info={"dir_src":src_dir,"dir_out":out_dir,"info_cam":meta_cam_info}

    print("meta_info:",meta_info)
    with open(os.path.join(out_dir,'meta_info.json'), 'w') as f:
        json.dump(meta_info, f, separators=(',', ':'))
        
    
   