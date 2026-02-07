import numpy as np
import os
import cv2
from tqdm import tqdm

# This is to replace specific images with a placeholder in the specified camera folders.
dir_src_folder = '../assets/videos/extr_88_sync2'

dict_image_to_replace={'cam2':list(range(275,313))+[610,612,648,650], 
                       'cam3':list(range(546,600)), 
                       'cam4':list(range(323,430)), 
                       'cam5':list(range(109,204))+list(range(409,504)), 
                       'cam6':list(range(28,90))+list(range(323,390))+list(range(610,657)),
                       'cam7':[193,195]+list(range(465,504)),
                       'cam8':list(range(245,261))+[572,574,576], 
                       'cam9':list(range(109,204))+list(range(427,504))}
file_pattern = 'frame_{:04d}.png'  # Pattern for image filenames
image_size = (2160,3840, 3)  # Size of the placeholder image


for cam_tag in dict_image_to_replace.keys():
    cam_folder = os.path.join(dir_src_folder, cam_tag)
    if not os.path.exists(cam_folder):
        print(f"Camera folder {cam_folder} does not exist. Skipping.")
        continue
    
    print(f"Replacing images in {cam_tag} with placeholder...")
    for cid in tqdm(dict_image_to_replace[cam_tag]):
        image_file = os.path.join(cam_folder, file_pattern.format(cid))
        if not os.path.exists(image_file):
            print(f"Image file {image_file} does not exist. Skipping.")
            continue

        placeholder = np.zeros(image_size, dtype=np.uint8) + 255
        cv2.imwrite(image_file, placeholder)
        

