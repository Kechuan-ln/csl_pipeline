from easydict import EasyDict as edict
import matplotlib.cm as cm
import argparse

IMG_FORMAT = "frame_{:08d}.jpg"
IMG_FORMAT_IO = "frame_%08d.jpg"

VIT_JOINTS_NAME = ('Nose', 'L_Eye', 'R_Eye', 'L_Ear', 'R_Ear', 'L_Shoulder', 'R_Shoulder', 'L_Elbow', 'R_Elbow', 'L_Wrist', 'R_Wrist','L_Hip','R_Hip','L_Knee','R_Knee', 'L_Ankle','R_Ankle')
VIT_SKELETON= [(0, 1), (0, 2), (1, 3), (2, 4), (5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),]
VIT_SKELETON_COLOR = ['red','green','red','green','red','red','red','green','green','red','green','red','red','red','green','green']
PATH_ASSETS = '../assets/'
PATH_ASSETS_VIDEOS = '../assets/videos/'
PATH_ASSETS_BBOX_AUTO = '../assets/results/bbox/auto/'
PATH_ASSETS_BBOX_MANUAL = '../assets/results/bbox/manual/'

PATH_ASSETS_KPT2D_AUTO = '../assets/results/vitpose/'
PATH_ASSETS_KPT2D_MANUAL = '../assets/results/manual2d/'
PATH_ASSETS_KPT2D_MANUAL_PF = '../assets/results/manual2d/pf/'
PATH_ASSETS_KPT2D_CHECK = '../assets/results/vitpose_check/'

PATH_ASSETS_KPT3D = '../assets/results/triangulation/'
PATH_ASSETS_REFINED_KPT3D = '../assets/results/refined3d/'
PATH_ASSETS_KPT3D_CHECK = '../assets/results/check3d/'

COCO_SKELETON = {
                'left_leg': [13, 15], ## l-knee to l-ankle
                'right_leg': [14, 16], ## r-knee to r-ankle
                'left_thigh': [11, 13], ## l-hip to l-knee
                'right_thigh': [12, 14], ## r-hip to r-knee
                'hip': [11, 12], ## l-hip to r-hip
                'left_torso': [5, 11], ## l-shldr to l-hip
                'right_torso': [6, 12], ## r-shldr to r-hip
                'left_bicep': [5, 7], ## l-shldr to l-elbow
                'right_bicep': [6, 8], ## r-shldr to r-elbow
                'shoulder': [5, 6], ## l-shldr to r-shldr
                'left_hand': [7, 9], ## l-elbow to l-wrist
                'right_hand': [8, 10], ## r-elbow to r-wrist
                'left_face': [1, 0], ## l-eye to nose
                'right_face': [2, 0], ## r-eye to nose
                'face': [1, 2], ## l-eye to r-eye
                'left_ear': [1, 3], ## l-eye to l-ear
                'right_ear': [2, 4], ## l-eye to r-ear
                'left_neck': [3, 5], ## l-ear to l-shldr
                'right_neck': [4, 6], ## r-ear to r-shldr
}
###----------------------------------------------------------------------------

COCO_SKELETON_FLIP_PAIRS = {
                    'leg':    ('left_leg', 'right_leg'),
                    'thigh':    ('left_thigh', 'right_thigh'),
                    'torso':    ('left_torso', 'right_torso'),
                    'bicep':    ('left_bicep', 'right_bicep'),
                    'hand':    ('left_hand', 'right_hand'),
                    'face':    ('left_face', 'right_face'),
                    'ear':    ('left_ear', 'right_ear'),
                    'neck':    ('left_neck', 'right_neck'),
                    }




def generate_keypoint_colors_matplotlib(num_keypoints):
    """Generate colors for keypoints using matplotlib colormap"""
    # Use 'tab20' colormap which has distinct colors, or 'Set1' which avoids green dominance
    cmap = cm.get_cmap('tab20')
    colors = []
    colors.append((255,255,255))
    for i in range(1, num_keypoints):
        rgba = cmap((i+5)%20)
        # Convert RGBA to BGR for OpenCV
        b, g, r = int(rgba[2]*255), int(rgba[1]*255), int(rgba[0]*255)
        colors.append((b, g, r))
    return colors

VIT_KEYPOINT_COLORS = generate_keypoint_colors_matplotlib(len(VIT_JOINTS_NAME))


cfg_annotation = edict()
cfg_annotation.POSE3D = edict()
cfg_annotation.POSE3D.KEYPOINTS_THRES = 0.5
cfg_annotation.POSE3D.NUM_ITERS = 1000
cfg_annotation.POSE3D.REPROJECTION_ERROR_EPSILON = 0.01

cfg_annotation.POSE3D.MIN_VIEWS = 2  # min views for triangulation
cfg_annotation.POSE3D.INCLUDE_CONFIDENCE = True  # include confidence in triangulation


cfg_annotation.REFINE_POSE3D = edict()
cfg_annotation.REFINE_POSE3D.DEBUG = True
cfg_annotation.REFINE_POSE3D.STD_THRES = 10  # +- std deviation allowed for inliers
cfg_annotation.REFINE_POSE3D.WINDOW_LENGTH = 10
cfg_annotation.REFINE_POSE3D.MOTION_THRES = 0.5 # in meter #300  # in pixels 4k



cfg_annotation.FIT_POSE3D = edict()
cfg_annotation.FIT_POSE3D.DEBUG = True
cfg_annotation.FIT_POSE3D.NUM_EPOCHS = 10
cfg_annotation.FIT_POSE3D.NUM_ITERS = 500
cfg_annotation.FIT_POSE3D.LR = 0.1
cfg_annotation.FIT_POSE3D.MAX_ITER = 20
cfg_annotation.FIT_POSE3D.INIT_POSE_LOSS_WEIGHT = 1
cfg_annotation.FIT_POSE3D.SYMMETRY_LOSS_WEIGHT = 1
cfg_annotation.FIT_POSE3D.TEMPORAL_LOSS_WEIGHT = 1
cfg_annotation.FIT_POSE3D.LIMB_LENGTH_LOSS_WEIGHT = 1
cfg_annotation.FIT_POSE3D.FTOL = 1e-4
cfg_annotation.FIT_POSE3D.GLOBAL_ITERS = 3



def get_args_parser():
    parser = argparse.ArgumentParser(description='',
                                     add_help=True,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--recording_tag', type=str, default='sync_9122', help='recording name')
    parser.add_argument('--path_camera',type=str, default='', help='Path to the camera meta json file, if empty, use calibration.json under --recording_tag')
    parser.add_argument('--cam_keys', type=str, default='', help='camera keys to use, split by comma, if empty, use all cameras')
    parser.add_argument('--only_frames_with_manual', action='store_true', help='only use frames with manual annotation for triangulation')

    parser.add_argument('--use_manual_annotation', action='store_true', help='use manual annotation for triangulation')
    parser.add_argument('--use_before_refinement', action='store_true', help='if true, use 3D before refinement for checking')
    parser.add_argument('--threshold_det_conf', type=float, default=0.8, help='threshold for 2D joint scores')
    parser.add_argument('--threshold_reproj_err', type=float, default=40., help='threshold for 2D reprojection scores')
    parser.add_argument('--min_cam', type=int, default=2, help='threshold for qualified camera detections')
    parser.add_argument('--verbose', action='store_true', help='verbose check the image and 2D joints')
    return parser.parse_args()

def update_cfg_annotation(args):
    cfg_annotation.POSE3D.KEYPOINTS_THRES = args.threshold_det_conf
    cfg_annotation.POSE3D.MIN_VIEWS = args.min_cam
    cfg_annotation.POSE3D.REPROJECTION_ERROR_EPSILON = 10
    
    return cfg_annotation
