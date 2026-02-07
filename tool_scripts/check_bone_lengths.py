import numpy as np
import os
import sys
sys.path.append('..')
from utils.constants import PATH_ASSETS,COCO_SKELETON
from utils.io_utils import load_3d_keypoint_json

def check_bone_lengths(joints3d):
    """
    Check the lengths of bones in the given 3D joint positions.
    """
    bone_lengths = {}
    for bone_name, joint_ids in COCO_SKELETON.items():
        joint1 = joints3d[joint_ids[0]]
        joint2 = joints3d[joint_ids[1]]
        if joint1[3] < 0.9 or joint2[3] < 0.9:
            continue
        length = np.linalg.norm(np.array(joint1[:3]) - np.array(joint2[:3]))
        bone_lengths[bone_name] = length
    return bone_lengths



if __name__ == "__main__":
    path_json = os.path.join(PATH_ASSETS, 'results', 'refined3d', 'sync_10154_auto')
    print(path_json)
    json_data = load_3d_keypoint_json(path_json)

    overall_bone_lengths = {}
    for key, value in json_data.items():
        joints3d = value['refined_3d']
        cbone_lengths = check_bone_lengths(joints3d)
        for bone_name, length in cbone_lengths.items():
            if bone_name not in overall_bone_lengths:
                overall_bone_lengths[bone_name] = []
            overall_bone_lengths[bone_name].append(length)

    # and then aggregate the info
    for bone_name, lengths in overall_bone_lengths.items():
        avg_length = np.mean(lengths)
        std_length = np.std(lengths)
        
        print(f"Bone {bone_name}: Average Length = {avg_length*100:.2f} cm; Standard Deviation = {std_length*100:.2f} cm")



    portion = 0.998
    print(f"\nConsidering middle {portion*100:.2f}% lengths:")
    for bone_name, lengths in overall_bone_lengths.items():        
        half_portion = (1-portion)/2.
        lengths = np.sort(lengths)
        lengths = lengths[int(half_portion*len(lengths)): int((1-half_portion)*len(lengths))]

        std_length_portion = np.std(lengths)
        avg_length_portion = np.mean(lengths)
        print(f"Bone {bone_name}: Average = {avg_length_portion*100:.2f} cm; Standard Deviation = {std_length_portion*100:.2f} cm")
