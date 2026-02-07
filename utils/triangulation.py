
import torch
import cv2
import os
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import least_squares


from utils.constants import VIT_JOINTS_NAME, VIT_SKELETON, VIT_SKELETON_COLOR
from utils.plot_utils import vis_keypoints_with_skeleton



try:
    from aniposelib.cameras import Camera, CameraGroup
except ImportError:
    pass


def triangulate(cam_grp, p2ds, scores, score_threshold=0.5, use_ransac=True, min_cams=2):
    n_cams=p2ds.shape[0]
    out_shape=p2ds.shape[1:-1]
    p2ds[scores < score_threshold] = np.nan

    p2ds_flat = p2ds.reshape(n_cams, -1, 2)
    scores_flat = scores.reshape(n_cams, -1)

    #undistort should be True, given the description of cv2.undistortPoints
    if use_ransac:
        p3ds_flat, _, _, _ = cam_grp.triangulate_ransac(p2ds_flat, min_cams=min_cams)
    else:
        p3ds_flat = cam_grp.triangulate(p2ds_flat)
    reprojerr_flat = cam_grp.reprojection_error(p3ds_flat, p2ds_flat, mean=True)

    p3ds=p3ds_flat.reshape(out_shape+(3,))
    reprojerr=reprojerr_flat.reshape(out_shape)

    return p3ds, reprojerr



def create_camera_group(list_camera_tags, dict_cam_params):
    list_cameras = []
    for ccam_key in list_camera_tags:
        cam_param = dict_cam_params[ccam_key]
        camera = Camera(matrix=cam_param['K'],
            rvec=cam_param['rvec'],
            tvec=cam_param['tvec'],
            name = ccam_key)
        list_cameras.append(camera)
    cam_grp = CameraGroup(list_cameras)
    return cam_grp


##------------------------------------------------------------------------------------
## performs triangulation
class Triangulator: 
    def __init__(self, cfg, cam_keys, cam_params):
        
        self.cfg = cfg
        self.cam_keys = cam_keys
        self.cam_params = cam_params

        self.keypoint_thres = self.cfg.POSE3D.KEYPOINTS_THRES
        self.n_iters = self.cfg.POSE3D.NUM_ITERS
        self.reprojection_error_epsilon = self.cfg.POSE3D.REPROJECTION_ERROR_EPSILON
        self.min_views = self.cfg.POSE3D.MIN_VIEWS 
        self.include_confidence = self.cfg.POSE3D.INCLUDE_CONFIDENCE
        
        self.num_keypoints = len(VIT_JOINTS_NAME)
        
        # Build projection matrices for each camera
        self.proj_matrices = []
        for cam_key in cam_keys:
            cam_param = cam_params[cam_key]
            # Build projection matrix P = K[R|t]
            R, _ = cv2.Rodrigues(cam_param['rvec'])
            t = cam_param['tvec'].reshape(3, 1)
            Rt = np.hstack([R, t])
            P = cam_param['K'] @ Rt
            self.proj_matrices.append(P)
        
        self.proj_matrices = np.array(self.proj_matrices)
        


    # ##-----------------------------------------
    def run(self, kpt_2ds, kpt_scores,verbose=False):
        """
        Simplified run method for direct triangulation from 2D keypoints.
        
        Returns:
            kpt_3ds: numpy array of shape (num_keypoints, 3) - triangulated 3D keypoints
            kpt_3ds_error: numpy array of shape (num_keypoints,) - reprojection errors (if return_error=True)
        """
        kpt_3ds = np.full((self.num_keypoints, 3), np.nan)
        kpt_3ds_error = np.full((self.num_keypoints,), np.nan)
        
        # Triangulate each keypoint
        for keypoint_idx in range(self.num_keypoints):
            # Get valid cameras for this keypoint
            valid_cameras = kpt_scores[:, keypoint_idx] > self.keypoint_thres
            
            if np.sum(valid_cameras) < self.min_views:
                if verbose:
                    print(f'{keypoint_idx} {VIT_JOINTS_NAME[keypoint_idx]} - insufficient detection ({np.sum(valid_cameras)} < {self.min_views})')
                continue


            # Get 2D points and scores for valid cameras
            valid_kpt_2ds = kpt_2ds[valid_cameras, keypoint_idx, :]
            valid_scores = kpt_scores[valid_cameras, keypoint_idx]
            valid_proj_matrices = self.proj_matrices[valid_cameras]
            
            # Create points array in the format expected by triangulate_ransac
            points = np.column_stack([valid_kpt_2ds, valid_scores])
            
            # Triangulate this keypoint
            try:
                point_3d, inlier_views, reprojection_error_vector = self.triangulate_ransac(
                    valid_proj_matrices, points,
                    n_iters=self.n_iters,
                    reprojection_error_epsilon=self.reprojection_error_epsilon,
                    direct_optimization=True
                )
                
                # Check if we have enough inliers
                if len(inlier_views) >= self.min_views:
                    kpt_3ds[keypoint_idx] = point_3d
                    kpt_3ds_error[keypoint_idx] = reprojection_error_vector.mean()
                    
                    # verbose
                    valid_cam_keys = [self.cam_keys[i] for i in np.where(valid_cameras)[0]]
                    inlier_cam_keys = [valid_cam_keys[i] for i in inlier_views]
                    if verbose:
                        print(f'{keypoint_idx} {VIT_JOINTS_NAME[keypoint_idx]} kps_error:{reprojection_error_vector.mean():.4f}, inliers: {inlier_cam_keys}')
                elif verbose:
                    print(f'{keypoint_idx} {VIT_JOINTS_NAME[keypoint_idx]} - insufficient inliers, kps_error: {reprojection_error_vector.mean():.4f}, inliers: {inlier_cam_keys}')

            except Exception as e:
                print(f"Error triangulating keypoint {keypoint_idx} ({VIT_JOINTS_NAME[keypoint_idx]}): {e}")
                continue
        
        return kpt_3ds, kpt_3ds_error
        
    

    ##-----------------------------------------
    # https://github.com/karfly/learnable-triangulation-pytorch/blob/9d1a26ea893a513bdff55f30ecbfd2ca8217bf5d/mvn/models/triangulation.py#L72
    def triangulate_ransac(self, proj_matricies, points, n_iters=50, reprojection_error_epsilon=0.1, direct_optimization=True):
        assert len(proj_matricies) == len(points)
        assert len(points) >= 2

        proj_matricies = np.array(proj_matricies)
        points = np.array(points)

        n_views = len(points)

        # determine inliers
        view_set = set(range(n_views))
        inlier_set = set()


        ## create a list of all possible pairs of views
        view_pairs = []
        for i in range(n_views):
            for j in range(i+1, n_views):
                view_pairs.append([i, j])
        
        ## iterate over all possible pairs of views
        for i in range(len(view_pairs)):
            sampled_views = view_pairs[i]

        # for i in range(n_iters):
        #     sampled_views = sorted(random.sample(view_set, 2)) ## sample two views

            keypoint_3d_in_base_camera = self.triangulate_point_from_multiple_views_linear(proj_matricies[sampled_views], points[sampled_views])
            reprojection_error_vector = self.calc_reprojection_error_matrix(np.array([keypoint_3d_in_base_camera]), points, proj_matricies)[0]

            new_inlier_set = set(sampled_views)
            for view in view_set:
                current_reprojection_error = reprojection_error_vector[view]

                if current_reprojection_error < reprojection_error_epsilon:
                    new_inlier_set.add(view)

            if len(new_inlier_set) > len(inlier_set):
                inlier_set = new_inlier_set

        # triangulate using inlier_set
        if len(inlier_set) == 0:
            inlier_set = view_set.copy()

        ##-------------------------------
        inlier_list = np.array(sorted(inlier_set))
        inlier_proj_matricies = proj_matricies[inlier_list]
        inlier_points = points[inlier_list]

        keypoint_3d_in_base_camera = self.triangulate_point_from_multiple_views_linear(inlier_proj_matricies, inlier_points, self.include_confidence)
        reprojection_error_vector = self.calc_reprojection_error_matrix(np.array([keypoint_3d_in_base_camera]), inlier_points, inlier_proj_matricies)[0]
        #reprojection_error_mean = np.mean(reprojection_error_vector)

        #keypoint_3d_in_base_camera_before_direct_optimization = keypoint_3d_in_base_camera
        #reprojection_error_before_direct_optimization = reprojection_error_mean

        # direct reprojection error minimization
        if direct_optimization:
            def residual_function(x):
                reprojection_error_vector = self.calc_reprojection_error_matrix(np.array([x]), inlier_points, inlier_proj_matricies)[0]
                residuals = reprojection_error_vector
                return residuals

            x_0 = np.array(keypoint_3d_in_base_camera)
            res = least_squares(residual_function, x_0, loss='huber', method='trf')

            keypoint_3d_in_base_camera = res.x
            reprojection_error_vector = self.calc_reprojection_error_matrix(np.array([keypoint_3d_in_base_camera]), inlier_points, inlier_proj_matricies)[0]
            #reprojection_error_mean = np.mean(reprojection_error_vector)

        return keypoint_3d_in_base_camera, inlier_list, reprojection_error_vector

    ##-----------------------------------------
    # https://github.com/karfly/learnable-triangulation-pytorch/blob/9d1a26ea893a513bdff55f30ecbfd2ca8217bf5d/mvn/utils/multiview.py#L113
    def triangulate_point_from_multiple_views_linear(self, proj_matricies, points, include_confidence=True):
        """Triangulates one point from multiple (N) views using direct linear transformation (DLT).
        For more information look at "Multiple view geometry in computer vision",
        Richard Hartley and Andrew Zisserman, 12.2 (p. 312).
        Args:
            proj_matricies numpy array of shape (N, 3, 4): sequence of projection matricies (3x4)
            points numpy array of shape (N, 3): sequence of points' coordinates and confidence
        Returns:
            point_3d numpy array of shape (3,): triangulated point
        """
        assert len(proj_matricies) == len(points)

        points_confidence = points[:, 2].copy()
        points = points[:, :2].copy()

        ###-----normalize points_confidence-----
        points_confidence /= points_confidence.max()

        n_views = len(proj_matricies)
        A = np.zeros((2 * n_views, 4))
        for j in range(len(proj_matricies)):
            A[j * 2 + 0] = points[j][0] * proj_matricies[j][2, :] - proj_matricies[j][0, :]
            A[j * 2 + 1] = points[j][1] * proj_matricies[j][2, :] - proj_matricies[j][1, :]

            ## weight by the point confidence
            if include_confidence == True:
                A[j * 2 + 0] *= points_confidence[j]
                A[j * 2 + 1] *= points_confidence[j]

        u, s, vh =  np.linalg.svd(A, full_matrices=False)
        point_3d_homo = vh[3, :]

        point_3d = self.homogeneous_to_euclidean(point_3d_homo)

        return point_3d

    ##-----------------------------------------
    # https://github.com/karfly/learnable-triangulation-pytorch/blob/9d1a26ea893a513bdff55f30ecbfd2ca8217bf5d/mvn/utils/multiview.py#L186
    def calc_reprojection_error_matrix(self, keypoints_3d, keypoints_2d_list, proj_matricies):
        reprojection_error_matrix = []
        for keypoints_2d, proj_matrix in zip(keypoints_2d_list, proj_matricies):

            if len(keypoints_2d) == 3:
                keypoints_2d = keypoints_2d[:2] ## chop off the confidence

            keypoints_2d_projected = self.project_3d_points_to_image_plane_without_distortion(proj_matrix, keypoints_3d)
            reprojection_error = 1 / 2 * np.sqrt(np.sum((keypoints_2d - keypoints_2d_projected) ** 2, axis=1))
            reprojection_error_matrix.append(reprojection_error)

        return np.vstack(reprojection_error_matrix).T

    ##-----------------------------------------
    def project_3d_points_to_image_plane_without_distortion(self, proj_matrix, points_3d, convert_back_to_euclidean=True):
        """Project 3D points to image plane not taking into account distortion
        Args:
            proj_matrix numpy array or torch tensor of shape (3, 4): projection matrix
            points_3d numpy array or torch tensor of shape (N, 3): 3D points
            convert_back_to_euclidean bool: if True, then resulting points will be converted to euclidean coordinates
                                            NOTE: division by zero can be here if z = 0
        Returns:
            numpy array or torch tensor of shape (N, 2): 3D points projected to image plane
        """
        if isinstance(proj_matrix, np.ndarray) and isinstance(points_3d, np.ndarray):
            result = self.euclidean_to_homogeneous(points_3d) @ proj_matrix.T
            if convert_back_to_euclidean:
                result = self.homogeneous_to_euclidean(result)
            return result
        elif torch.is_tensor(proj_matrix) and torch.is_tensor(points_3d):
            result = self.euclidean_to_homogeneous(points_3d) @ proj_matrix.t()
            if convert_back_to_euclidean:
                result = self.homogeneous_to_euclidean(result)
            return result
        else:
            raise TypeError("Works only with numpy arrays and PyTorch tensors.")

    ##-----------------------------------------
    # https://github.com/karfly/learnable-triangulation-pytorch/blob/9d1a26ea893a513bdff55f30ecbfd2ca8217bf5d/mvn/utils/multiview.py#L72
    def homogeneous_to_euclidean(self, points):
        """Converts homogeneous points to euclidean
        Args:
            points numpy array or torch tensor of shape (N, M + 1): N homogeneous points of dimension M
        Returns:
            numpy array or torch tensor of shape (N, M): euclidean points
        """
        if isinstance(points, np.ndarray):
            return (points.T[:-1] / points.T[-1]).T
        elif torch.is_tensor(points):
            return (points.transpose(1, 0)[:-1] / points.transpose(1, 0)[-1]).transpose(1, 0)
        else:
            raise TypeError("Works only with numpy arrays and PyTorch tensors.")

    ##-----------------------------------------
    # https://github.com/karfly/learnable-triangulation-pytorch/blob/9d1a26ea893a513bdff55f30ecbfd2ca8217bf5d/mvn/utils/multiview.py#L55
    def euclidean_to_homogeneous(self, points):
        """Converts euclidean points to homogeneous
        Args:
            points numpy array or torch tensor of shape (N, M): N euclidean points of dimension M
        Returns:
            numpy array or torch tensor of shape (N, M + 1): homogeneous points
        """
        if isinstance(points, np.ndarray):
            return np.hstack([points, np.ones((len(points), 1))])
        elif torch.is_tensor(points):
            return torch.cat([points, torch.ones((points.shape[0], 1), dtype=points.dtype, device=points.device)], dim=1)
        else:
            raise TypeError("Works only with numpy arrays and PyTorch tensors.")
        





# utils functions


def compute_frame_joint_reprojection_error(dict_kpt2ds, kpt_3d, dict_cam_params, cam_keys, triangulation_threshold=0.5):
    '''
    dict_kpt2ds: dict of 2D keypoints for each camera, {cam_key: (17, 3) [x, y, confidence]}
    kpt_3d: (17, 3) array of 3D keypoints
    dict_cam_params: dict of camera parameters, {cam_key: {'rvec': rvec, 'tvec': tvec, 'K': K}}
    cam_keys: list of camera keys
    '''
    # Calculate reprojection error between dict_kpt2ds and kpt_3d
    kpt_3d_1 = kpt_3d.reshape(-1, 1, 3).astype(np.float32)

    reproj_err = np.full((len(VIT_JOINTS_NAME), len(cam_keys)), np.nan, dtype=np.float32)
    dict_reproj_err = {}
    
    for cam_idx, ccam_key in enumerate(cam_keys):
        if ccam_key not in dict_kpt2ds:
            continue

        # Get camera parameters
        cam_param = dict_cam_params[ccam_key]
        rvec = cam_param['rvec']
        tvec = cam_param['tvec']
        K = cam_param['K']
        
        # Get 2D detections for this camera
        kpt_2d_conf = dict_kpt2ds[ccam_key]  # Shape: (17, 3) [x, y, confidence]
        kpt_2d = kpt_2d_conf[:, :2]           # Shape: (17, 2) [x, y]
        kpt_conf = kpt_2d_conf[:, 2]          # Shape: (17,) [confidence]

        # Project 3D joints to 2D for this camera
        projected_2d, _ = cv2.projectPoints(kpt_3d_1, rvec, tvec, K, None)
        projected_2d = projected_2d.reshape(-1, 2)

        reproj_err[:, cam_idx] = np.linalg.norm(kpt_2d - projected_2d, axis=1)  # Shape: (17,)

        # set if kpt_conf is below threshold or kpt_3d is NaN
        reproj_err[:, cam_idx][kpt_conf < triangulation_threshold] = np.nan
        reproj_err[:, cam_idx][np.isnan(kpt_3d).any(axis=1)] = np.nan

        for joint_idx in range(len(VIT_JOINTS_NAME)):
            if kpt_conf[joint_idx] < triangulation_threshold or np.isnan(kpt_3d[joint_idx]).any():
                continue
                            
            error = np.linalg.norm(kpt_2d[joint_idx] - projected_2d[joint_idx])
            reproj_err[joint_idx, cam_idx] = error
            

        dict_reproj_err[ccam_key] = reproj_err[:, cam_idx].copy()  # Shape: (17,) per camera
        dict_reproj_err[ccam_key][np.isnan(reproj_err[:, cam_idx])] = -1.0


    mean_proj_nonan = np.mean(reproj_err[~np.isnan(reproj_err)])
    return dict_reproj_err, mean_proj_nonan
    


def visulaize_triangulation_results(dict_img_bgr, dict_cam_params, kpt_3d_valid, kpt_3d_gt, text_to_vis, cam_keys, input_zup=True, show_reproj_text=True, show_3d=True):

    kpt_3d_1 =  kpt_3d_valid[:, :3].reshape(-1, 1, 3).astype(np.float32)
    dict_images = {}
    for ccam_key in cam_keys:
        img_bgr = dict_img_bgr[ccam_key]
        cam_param = dict_cam_params[ccam_key]
        rvec = cam_param['rvec']
        tvec = cam_param['tvec']
        K = cam_param['K']

        # Project 3D joints to 2D
        projected_2d, _ = cv2.projectPoints(kpt_3d_1, rvec, tvec, K, None)
        projected_2d = projected_2d.reshape(-1, 2)

        img_bgr = vis_keypoints_with_skeleton(img_bgr,
                                            np.concatenate([projected_2d, kpt_3d_valid[:, 3:4]], axis=-1), 
                                            VIT_SKELETON, 
                                            bbox_xyxy=None, kp_thre=0., 
                                            kps_name=None)
                    
        # Add text showing error metrics
        if show_reproj_text:
            y_offset = 100
            mean_error = text_to_vis['mean_error']
            if mean_error is not None:
                error_text = f"3D Diff: {(100*mean_error):.1f}cm"
                cv2.putText(img_bgr, error_text, (100, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 
                        3., (0, 255, 0), 5, cv2.LINE_AA)
                y_offset += 100

            mean_proj = text_to_vis['mean_proj']        
            reproj_text = f"Reproj Err: {mean_proj:.2f}px"
            cv2.putText(img_bgr, reproj_text, (100, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 
                    3., (0, 255, 255), 5, cv2.LINE_AA)
            
        if not show_3d:
            dict_images[ccam_key] = img_bgr
            continue

        # Create 3D plot
        fig = plt.figure(figsize=(8, 8))
        ax = fig.add_subplot(111, projection='3d')


        # Set viewing angle (elevation, azimuth)
        ax.view_init(elev=5, azim=45)
        
        
        # Plot ground truth 3D joints (blue) if available
        if kpt_3d_gt is not None:
            # Draw ground truth skeleton connections (blue lines)
            for connection in VIT_SKELETON:
                joint1_idx, joint2_idx = connection
                
                joint1 = kpt_3d_gt[joint1_idx,:3]
                joint2 = kpt_3d_gt[joint2_idx,:3]
                if not input_zup:
                    joint1 = joint1[...,[0,2,1]].copy()
                    joint2 = joint2[...,[0,2,1]].copy()
                    joint1[...,2]*=-1
                    joint2[...,2]*=-1

                if kpt_3d_gt[joint1_idx, 3] > 0 and kpt_3d_gt[joint2_idx, 3] > 0:
                    ax.plot([joint1[0], joint2[0]], [joint1[1], joint2[1]], [joint1[2], joint2[2]], 
                        color='blue', alpha=0.8, linewidth=2)
    

        # Draw predicted skeleton connections (green lines)
        for connection, ccolor in zip(VIT_SKELETON, VIT_SKELETON_COLOR):
            joint1_idx, joint2_idx = connection
            
            joint1 = kpt_3d_valid[joint1_idx,:3]
            joint2 = kpt_3d_valid[joint2_idx,:3]
            if not input_zup:
                joint1 = joint1[...,[0,2,1]].copy()
                joint2 = joint2[...,[0,2,1]].copy()
                joint1[...,2]*=-1
                joint2[...,2]*=-1
            if kpt_3d_valid[joint1_idx, 3] > 0 and kpt_3d_valid[joint2_idx, 3] > 0:  # Only draw if both joints are valid
                ax.plot([joint1[0], joint2[0]], [joint1[1], joint2[1]], [joint1[2], joint2[2]], 
                    color=ccolor, alpha=0.6, linewidth=2)
                    
        # Save 3D plot to temporary file
        temp_3d_path = f"temp_3d.png"
        plt.savefig(temp_3d_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        # Load 3D plot as image
        plot_3d_img = cv2.imread(temp_3d_path)
        os.remove(temp_3d_path)
        
        # Resize images to same height for concatenation
        h1, w1 = img_bgr.shape[:2]
        h2, w2 = plot_3d_img.shape[:2]
        
        if h1 != h2:
            if h1 > h2:
                plot_3d_img = cv2.resize(plot_3d_img, (int(w2 * h1 / h2), h1))
            else:
                img_bgr = cv2.resize(img_bgr, (int(w1 * h2 / h1), h2))
        
        # Concatenate 2D and 3D visualizations horizontally
        concatenated_img = np.hstack([img_bgr, plot_3d_img])
        dict_images[ccam_key] = concatenated_img

    return dict_images


def visualise_annotation_needed_joints(img_bgr, detection_2d, reprojection_2d, flags_need_annotation, threshold_det_conf, thickness=4):
    """Visualize 2D keypoints and reprojections on the image."""
    vis_img = img_bgr.copy()

    #str_info = [f"Frame #{frame_id:06d}","Need Annotation:"]
    #pt_str_info = 30

    #info_img = np.zeros((vis_img.shape[0], 450, 3), dtype=np.uint8)+255
    #for i, line in enumerate(str_info):
    #    cv2.putText(info_img, line, (0, pt_str_info), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 2)
    #    pt_str_info += 40


    for sk in VIT_SKELETON:
        cpt1 = sk[0]
        cpt2 = sk[1]
        if reprojection_2d[cpt1,0]>0 and reprojection_2d[cpt2,0]>0:
            pt1 = (int(reprojection_2d[cpt1,0]), int(reprojection_2d[cpt1,1]))
            pt2 = (int(reprojection_2d[cpt2,0]), int(reprojection_2d[cpt2,1]))
            cv2.line(vis_img, pt1, pt2, (153,0,0), thickness)

    for i in range(detection_2d.shape[0]):
        det_x, det_y, det_conf = detection_2d[i]
        reproj_x, reproj_y = reprojection_2d[i]

        if reproj_x>0 and reproj_y>0:
            cv2.circle(vis_img, (int(reproj_x), int(reproj_y)), 4, (153,0,0), -1)

        if det_conf>threshold_det_conf and flags_need_annotation[i]:
            color = (0,0,255)#VIT_KEYPOINT_COLORS[i]#(0,0,255) if not flags_need_annotation[i] else VIT_KEYPOINT_COLORS[i]
            cv2.circle(vis_img, (int(det_x), int(det_y)), 8, color, -1)
            cv2.putText(vis_img, f"{VIT_JOINTS_NAME[i]}", (int(det_x)-10, int(det_y)-20), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
            #pt_str_info = 40*i + 70
            #cv2.putText(info_img, f"#{i:02d}: {VIT_JOINTS_NAME[i]}", (0, pt_str_info), cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 2)
            

    #vis_img = np.hstack((vis_img, info_img))

    # resize to 720p height
    scale = 720/vis_img.shape[0]
    vis_img = cv2.resize(vis_img, (int(vis_img.shape[1]*scale), 720))

    return vis_img
