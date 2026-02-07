import os
import sys
sys.path.append('..')

import cv2

from dataset.recording import Recording
from utils.constants import PATH_ASSETS_VIDEOS, get_args_parser

def main():
    args = get_args_parser()
    path_root_dir = os.path.join(PATH_ASSETS_VIDEOS, args.recording_tag)
    recording_name = args.recording_tag.split('/')[-2]
    load_undistort_images = 'undistort' in args.recording_tag

    dataset = Recording(root_dir = path_root_dir,
                        path_cam_meta = None,
                        logger = None,
                        recording_name = recording_name,
                        load_undistort_images = load_undistort_images)
    
    dataset.save_images_to_lmdb(overwrite=False)


    image_rgb=dataset.get_image_from_lmdb("cam2/frame_00000001.jpg")
    image_bgr = image_rgb[..., ::-1].copy()
    cv2.imshow("image",image_bgr)
    cv2.waitKey(0)


if __name__ == "__main__":
    main()
