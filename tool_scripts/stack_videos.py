import os
import glob
import sys
sys.path.append('..')
from utils.io_utils import stack_videos_grid, stack_images_grid,convert_mp4_to_looping_gif
from utils.constants import IMG_FORMAT


if False:
    dir_gradios = '../assets/results/vitpose_check/gradio'
    path_mp4s = glob.glob(os.path.join(dir_gradios, '*.mp4'))
    for path_mp4 in path_mp4s:
        convert_mp4_to_looping_gif(path_mp4)

    exit(0)


dir_root = '../assets/videos/sync_1101_gopro/'
path2 = os.path.join(dir_root, 'cam2/GX010200.MP4')
path3 = os.path.join(dir_root, 'cam3/GX010236.MP4')
path4 = os.path.join(dir_root, 'cam4/GX010217.MP4')
path_output = "../assets/videos/sync_1101_gopro.mp4"
# 4k video
stack_videos_grid([path2,path3, path4], path_output,rows=3, cols=1, scale_width=3840, scale_height=2160)
exit(0)
#exit(0)


paths = [f"../assets/results/check3d/sync_10154/cam{id}_manual_refined.mp4" for id in [2,3,4,5,6,7]]
output_path = "../assets/results/check3d/sync_10154/sync_10154_manual.mp4"
stack_videos_grid(paths, output_path,rows=3, cols=2, scale_width=1080, scale_height=720)



paths = [f"../assets/results/check3d/sync_10152/cam{id}_manual_refined.mp4" for id in [2,3,4,5,6,7]]
output_path = "../assets/results/check3d/sync_10152/sync_10152_manual.mp4"
stack_videos_grid(paths, output_path,rows=3, cols=2, scale_width=1080, scale_height=720)
exit(0)




#paths = [f"../assets/results/refined3d_check/sync_10154/cam{id}_auto.mp4" for id in [2,3,4,5,6,7]]
#output_path = "../assets/results/refined3d_check/sync_10154/sync_10154_auto.mp4"
#stack_six_videos_grid(paths, output_path)



dir_root = '../assets/results/check3d/sync_10154/'
cam_ids = [2,3,4,5,6,7]

tag = 'manual_refined'

#range_to_check = list(range(660,680))+list(range(1600,1610))+list(range(3726,3736))+list(range(290,310))+list(range(360,390))+list(range(6610,6630))+list(range(7715,7735))+list(range(1800,1820))+list(range(6830,6850))
path_to_check = glob.glob(os.path.join(dir_root, f'{tag}_cam2', '*.jpg'))
frame_ids = [int(os.path.basename(p).split('.')[0].split('_')[-1]) for p in path_to_check]
range_to_check = sorted(frame_ids)

for frame_id in range_to_check:
    image_paths = [os.path.join(dir_root, f'{tag}_cam{cam_id}', IMG_FORMAT.format(frame_id)) for cam_id in cam_ids]
    output_path =  os.path.join(dir_root, "results", f"frame_{frame_id:06d}_{tag}.jpg")
    if not os.path.exists(os.path.dirname(output_path)):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    stack_images_grid(image_paths, output_path, rows=3, cols=2)