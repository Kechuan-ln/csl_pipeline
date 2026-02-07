import os
from os import path
import glob
from natsort import natsorted

import sys
sys.path.append(path.dirname(path.dirname(path.dirname(path.dirname(path.abspath(__file__))))))
from utils.calib_utils import get_fps
from utils.io_utils import convert_video_to_images

from multical.io.logging import info

image_extensions = ['jpg', 'jpeg', 'png', 'ppm', 'bmp']
video_extensions = ['mp4', 'MP4']

def has_extension(extensions, filename):
    return any(filename.lower().endswith("." + extension) for extension in extensions)



def find_image_files(filepath, extensions=image_extensions):
    return [filename for filename in natsorted(os.listdir(filepath))
                if has_extension(extensions, path.join(filepath, filename))]

def find_unmatched_files(camera_paths, extensions):
  return {k:find_image_files(d, extensions) for k, d in camera_paths.items()}

def find_matching_files(camera_paths, extensions):
  camera_files = find_unmatched_files(camera_paths, extensions)
  return natsorted(set.intersection(*[set(files) for files in camera_files.values()]))


def find_cameras(base_dir, cameras, camera_pattern, extensions=image_extensions):
  if cameras is None or len(cameras) == 0:
    cameras = natsorted(find_nonempty_dirs(base_dir, extensions))
    cameras_videos = natsorted(find_nonempty_dirs(base_dir, ['mp4', 'MP4']))
    for dir_video in cameras_videos:
      if dir_video not in cameras:        
        cameras.append(dir_video)
        # here decompose the video into images
        video_path = glob.glob(path.join(base_dir, dir_video, f"*.MP4"))+ glob.glob(path.join(base_dir, dir_video, f"*.mp4"))
        if len(video_path) > 0:
          video_path = video_path[0]
          # load fps
          fps = get_fps(video_path)
          info(f"Decomposing video {video_path} into images, with fps {fps}")
          convert_video_to_images(video_path, path.join(base_dir, dir_video), min(10,fps))

  camera_pattern = camera_pattern or "{camera}" 
  return {camera:path.join(base_dir, camera_pattern.format(camera=camera)) for camera in cameras}

  


def find_nonempty_dirs(filepath, extensions=image_extensions):
    return [local_dir for local_dir in os.listdir(filepath)
      for abs_dir in [path.join(filepath, local_dir)]
      if path.isdir(abs_dir) and len(find_image_files(abs_dir, extensions)) > 0 
    ]



def find_images_matching(camera_dirs, extensions=image_extensions):
  image_names = find_matching_files(camera_dirs, extensions)
  return image_names, filenames(camera_dirs.values(), image_names)


def find_images_unmatched(camera_dirs, extensions=image_extensions):
  image_files = find_unmatched_files(camera_dirs, extensions)

  image_filenames = [[path.join(camera_dir, file) for file in image_names]
    for camera_dir, image_names in image_files.items()]

  return image_files.keys(), image_filenames


def filenames(camera_dirs, image_names):
  return [[path.join(camera_dir, image) for image in image_names]
    for camera_dir in camera_dirs]
