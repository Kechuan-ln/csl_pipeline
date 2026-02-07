
from multical.io.logging import setup_logging
from vis import visualize_ws

from structs.struct import struct, map_none, to_structs
import numpy as np
import os
import cv2
import json

from multical.config import *
from dataclasses import dataclass
import sys
sys.path.append('..')

# Override PATH_ASSETS_VIDEOS from environment variable before importing constants
PATH_ASSETS_VIDEOS = os.environ.get('PATH_ASSETS_VIDEOS', '../assets/videos/')
PATH_ASSETS = os.environ.get('PATH_ASSETS', '../assets/')

@dataclass
class Calibrate:
    """Run camera calibration"""
    paths  : PathOpts
    camera  : CameraOpts
    runtime    : RuntimeOpts
    optimizer  : OptimizerOpts
    vis : bool = False        # Visualize result after calibration

    def execute(self):
        if self.paths.image_path is not None:
            self.paths.image_path = os.path.join(PATH_ASSETS_VIDEOS, self.paths.image_path)
        if self.paths.output_path is not None:
            self.paths.output_path = os.path.join(PATH_ASSETS_VIDEOS, self.paths.output_path)   
        if self.camera.calibration is not None:
            self.camera.calibration = os.path.join(PATH_ASSETS_VIDEOS, self.camera.calibration)
        print(self)
        calibrate(self)



def draw(img, rvec, tvec, intr_mat, dist_coeff, square_length):
    n_squares = 3
    axis = np.float32([[n_squares*square_length,0,0], [0,n_squares*square_length,0], [0,0,n_squares*square_length], [0,0,0]]).reshape(-1,3)
    imgpts, jac = cv2.projectPoints(axis, rvec, tvec, intr_mat, dist_coeff)

    try:
        colors = {'ox': (0, 0, 255), 'oy': (0, 255, 0), 'oz': (255, 0, 0)}
        cv2.drawFrameAxes(img, intr_mat, dist_coeff, rvec, tvec, n_squares*square_length, thickness=1)
        #img = cv2.line(img, corner, tuple(imgpts[0].ravel().astype(int)),  colors['ox'], 5)
        #img = cv2.line(img, corner, tuple(imgpts[1].ravel().astype(int)),  colors['oy'], 5)
        #img = cv2.line(img, corner, tuple(imgpts[2].ravel().astype(int)),  colors['oz'], 5)
        cv2.putText(img, 'X', tuple(imgpts[0].ravel().astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 1,  colors['ox'], 2)
        cv2.putText(img, 'Y', tuple(imgpts[1].ravel().astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 1,  colors['oy'], 2)
        cv2.putText(img, 'Z', tuple(imgpts[2].ravel().astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 1,  colors['oz'], 2)
    except Exception as e:
        pass
    return img


def create_transform_matrix(R, T):
    transform = np.eye(4)
    transform[:3, :3] = R
    transform[:3, 3] = T.flatten()
    return transform

def decompose_transform_matrix(transform):
    R = transform[:3, :3]
    T = transform[:3, 3].reshape(3, 1)
    return R, T

def calibrate(args):
    np.set_printoptions(precision=4, suppress=True)

    # Use image path if not explicity specified
    output_path = args.paths.image_path or args.paths.output_path

    # Ensure output directory exists
    os.makedirs(output_path, exist_ok=True)

    ws = workspace.Workspace(output_path, args.paths.name)
    setup_logging(args.runtime.log_level, [ws.log_handler], log_file=path.join(output_path, f"{args.paths.name}.txt"))

    boards = find_board_config(args.paths.image_path, board_file=args.paths.boards)
    camera_images = find_camera_images(args.paths.image_path,
    args.paths.cameras, args.paths.camera_pattern, limit=args.paths.limit_images)

    initialise_with_images(ws, boards, camera_images, args.camera, args.runtime)
    optimize(ws, args.optimizer)

    ws.export()
    ws.dump()


    if args.vis:
        path_json = os.path.join(args.paths.image_path, 'calibration.json')
        with open(path_json, 'r') as f:
            data_calib = json.load(f)

        calib_world2base = data_calib['camera_world2base']
        calib_base2cam = data_calib['camera_base2cam']
        calib_intr = data_calib['cameras']


        detected_points = ws.detected_points


        for cam_id in range(len(camera_images.filenames)):
            for file_id, cfile_name_ in enumerate(camera_images.filenames[cam_id]):
                cfile_name = '/'.join(cfile_name_.split('/')[-2:])  # Get the last two parts of the path

                # image_path basename
                tag_path_image = args.paths.image_path.strip('/').split('/')[-1]
                dir_vis_to_save = os.path.join(args.paths.image_path,'..', 'vis', tag_path_image)
                path_vis_output = os.path.join(dir_vis_to_save, cfile_name)

                if file_id==0 and not os.path.exists(os.path.dirname(path_vis_output)):
                    os.makedirs(os.path.dirname(path_vis_output), exist_ok=True)

                cvis_img = cv2.imread(os.path.join(args.paths.image_path, cfile_name))


                try:
                    cdet = detected_points[cam_id][file_id][0]
                    #cv2.aruco.drawDetectedMarkers(cvis_img, cdet.marker_corners, cdet.marker_ids)
                    cv2.aruco.drawDetectedCornersCharuco(cvis_img, cdet.corners[:,np.newaxis], cdet.ids[:,np.newaxis], (0,255,255))
                except Exception as e:
                    info(f"Invalid board detection {path_vis_output}: {e}")
                    pass

                if f'{file_id}' in calib_world2base:
                    cam_tag = cfile_name.split('/')[0]
                    cworld2base = calib_world2base[f'{file_id}']
                    if cam_tag in calib_base2cam:
                        cbase2cam = calib_base2cam[cam_tag]
                    else:
                        cbase2cam = None
                        keys = list(calib_base2cam.keys())
                        for key in keys:
                            if key.startswith(f'{cam_tag}_'):
                                cbase2cam = calib_base2cam[key]
                                break
                        

                    intr_K = np.array(calib_intr[cam_tag]['K']).reshape(3,3)
                    dist_coeff = np.array(calib_intr[cam_tag]['dist']).flatten()

                    # Skip if no extrinsic found for this camera
                    if cbase2cam is None:
                        cv2.imwrite(path_vis_output, cvis_img)
                        continue

                    Rt_w2b = create_transform_matrix(np.array(cworld2base['R']), np.array(cworld2base['T']))
                    Rt_b2c = create_transform_matrix(np.array(cbase2cam['R']), np.array(cbase2cam['T']))
                    Rt_w2c = Rt_b2c @ Rt_w2b
                    
                    R_w2c_mat, T_w2c = decompose_transform_matrix(Rt_w2c)
                    R_w2c_vec, _ = cv2.Rodrigues(R_w2c_mat)                

                    _, first_board = list(boards.items())[0]
                    cvis_img = draw(cvis_img, R_w2c_vec, T_w2c, intr_K, dist_coeff, first_board.square_length)

                cv2.imwrite(path_vis_output, cvis_img)

    #visualize_ws(ws)



if __name__ == '__main__':
    run_with(Calibrate)
