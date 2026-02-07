import cv2
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


from PIL import Image

import math


def draw_bodypose(canvas, candidate, openpose_joints_name):
    stickwidth = 4
    limbSeq = [[2, 3], [2, 6], [3, 4], [4, 5], [6, 7], [7, 8], [2, 9], [9, 10], \
               [10, 11], [2, 12], [12, 13], [13, 14], [2, 1], [1, 15], [15, 17], \
               [1, 16], [16, 18], [3, 17], [6, 18]]

    colors = [[255, 0, 0], [255, 85, 0], [255, 170, 0], [255, 255, 0], [170, 255, 0], [85, 255, 0], [0, 255, 0], \
              [0, 255, 85], [0, 255, 170], [0, 255, 255], [0, 170, 255], [0, 85, 255], [0, 0, 255], [85, 0, 255], \
              [170, 0, 255], [255, 0, 255], [255, 0, 170], [255, 0, 85]]
    

    for index in range(18):
        if candidate[index][2]<0.3:
            continue
        x, y = candidate[index][0:2]
        cv2.circle(canvas, (int(x), int(y)), 4, colors[index], thickness=-1)
        cv2.putText(canvas, f"{openpose_joints_name[index]}", (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    
    for i in range(0):
        index = np.array(limbSeq[i])-1
        if candidate[index[0].astype(int)][2] < 0.3 or candidate[index[1].astype(int)][2] < 0.3:
            continue
        cur_canvas = canvas.copy()
        Y = candidate[index.astype(int), 0]
        X = candidate[index.astype(int), 1]
        mX = np.mean(X)
        mY = np.mean(Y)
        length = ((X[0] - X[1]) ** 2 + (Y[0] - Y[1]) ** 2) ** 0.5
        angle = math.degrees(math.atan2(X[0] - X[1], Y[0] - Y[1]))
        polygon = cv2.ellipse2Poly((int(mY), int(mX)), (int(length / 2), stickwidth), int(angle), 0, 360, 1)
        cv2.fillConvexPoly(cur_canvas, polygon, colors[i])
        canvas = cv2.addWeighted(canvas, 0.4, cur_canvas, 0.6, 0)
    return canvas


def draw_points(image, keypoints, scores, pose_keypoint_color, keypoint_score_threshold, radius, show_keypoint_weight):
    if pose_keypoint_color is not None:
        assert len(pose_keypoint_color) == len(keypoints)
    for kid, (kpt, kpt_score) in enumerate(zip(keypoints, scores)):
        x_coord, y_coord = int(kpt[0]), int(kpt[1])
        if kpt_score > keypoint_score_threshold:
            color = tuple(int(c) for c in pose_keypoint_color[kid])
            if show_keypoint_weight:
                cv2.circle(image, (int(x_coord), int(y_coord)), radius, color, -1)
                transparency = max(0, min(1, kpt_score))
                cv2.addWeighted(image, transparency, image, 1 - transparency, 0, dst=image)
            else:
                cv2.circle(image, (int(x_coord), int(y_coord)), radius, color, -1)
    return image

def draw_links(image, keypoints, scores, keypoint_edges, link_colors, keypoint_score_threshold, thickness, show_keypoint_weight, stick_width = 2):
    height, width, _ = image.shape
    if keypoint_edges is not None and link_colors is not None:
        assert len(link_colors) == len(keypoint_edges)
        for sk_id, sk in enumerate(keypoint_edges):
            x1, y1, score1 = (int(keypoints[sk[0], 0]), int(keypoints[sk[0], 1]), scores[sk[0]])
            x2, y2, score2 = (int(keypoints[sk[1], 0]), int(keypoints[sk[1], 1]), scores[sk[1]])
            if (
                x1 > 0
                and x1 < width
                and y1 > 0
                and y1 < height
                and x2 > 0
                and x2 < width
                and y2 > 0
                and y2 < height
                and score1 > keypoint_score_threshold
                and score2 > keypoint_score_threshold
            ):
                color = tuple(int(c) for c in link_colors[sk_id])
                if show_keypoint_weight:
                    X = (x1, x2)
                    Y = (y1, y2)
                    mean_x = np.mean(X)
                    mean_y = np.mean(Y)
                    length = ((Y[0] - Y[1]) ** 2 + (X[0] - X[1]) ** 2) ** 0.5
                    angle = math.degrees(math.atan2(Y[0] - Y[1], X[0] - X[1]))
                    polygon = cv2.ellipse2Poly(
                        (int(mean_x), int(mean_y)), (int(length / 2), int(stick_width)), int(angle), 0, 360, 1
                    )
                    cv2.fillConvexPoly(image, polygon, color)
                    transparency = max(0, min(1, 0.5 * (keypoints[sk[0], 2] + keypoints[sk[1], 2])))
                    cv2.addWeighted(image, transparency, image, 1 - transparency, 0, dst=image)
                else:
                    cv2.line(image, (x1, y1), (x2, y2), color, thickness=thickness)


def draw_box(image, bboxes, confidences, color=(0, 255, 0), thickness=2):
    """
    Draw bounding boxes with confidence scores on the image.
    
    Args:
        image: Input image (BGR format)
        bboxes: Array of bounding boxes in format [[x1, y1, x2, y2], ...]
        confidences: Array of confidence scores for each bbox
        color: Color for the bounding box (B, G, R)
        thickness: Thickness of the bounding box lines
    
    Returns:
        Image with drawn bounding boxes
    """
    img_with_boxes = image.copy()
    
    for i, (bbox, conf) in enumerate(zip(bboxes, confidences)):
        x1, y1, x2, y2 = map(int, bbox)
        
        # Draw bounding box
        cv2.rectangle(img_with_boxes, (x1, y1), (x2, y2), color, thickness)
        
        # Draw confidence score
        conf_text = f"Human: {conf:.2f}"
        text_size = cv2.getTextSize(conf_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
        
        # Position text above the bounding box
        text_x = x1
        text_y = y1 - 10 if y1 - 10 > 10 else y1 + text_size[1] + 10
        
        # Draw background rectangle for text
        cv2.rectangle(img_with_boxes, 
                     (text_x, text_y - text_size[1] - 5), 
                     (text_x + text_size[0] + 5, text_y + 5), 
                     color, -1)
        
        # Draw text
        cv2.putText(img_with_boxes, conf_text, (text_x + 2, text_y - 2), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    
    return img_with_boxes




def draw_box_with_tracking(image, bboxes, track_ids, confidences, color=(0, 255, 0), thickness=2):
    """
    Draw bounding boxes with track IDs and confidence scores.
    
    Args:
        image: Input image (BGR format)
        bboxes: Array of bounding boxes in format [[x1, y1, x2, y2], ...]
        track_ids: Array of track IDs for each bbox
        confidences: Array of confidence scores for each bbox
        color: Color for the bounding box (B, G, R)
        thickness: Thickness of the bounding box lines
    
    Returns:
        Image with drawn bounding boxes and track IDs
    """
    img_with_boxes = image.copy()
    
    for i, (bbox, track_id, conf) in enumerate(zip(bboxes, track_ids, confidences)):
        x1, y1, x2, y2 = map(int, bbox)
        
        # Use different colors for different track IDs
        track_color = (
            int((track_id * 50) % 255),
            int((track_id * 100) % 255), 
            int((track_id * 150) % 255)
        )
        
        # Draw bounding box
        cv2.rectangle(img_with_boxes, (x1, y1), (x2, y2), track_color, thickness)
        
        # Draw track ID and confidence
        text = f"ID:{track_id} {conf:.2f}"
        text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 3)[0]
        
        # Position text above the bounding box
        text_x = x1
        text_y = y1 - 10 if y1 - 10 > 10 else y1 + text_size[1] + 10
        
        # Draw background rectangle for text
        cv2.rectangle(img_with_boxes, 
                     (text_x, text_y - text_size[1] - 5), 
                     (text_x + text_size[0] + 5, text_y + 5), 
                     track_color, -1)
        
        # Draw text
        cv2.putText(img_with_boxes, text, (text_x + 2, text_y - 2), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255,255,255), 3, cv2.LINE_AA)
    
    return img_with_boxes

def vis_keypoints_with_skeleton(img, kps, kps_line, bbox_xyxy=None, kp_thre=0.4, kps_name=None):
    # img: np.array, shape (H, W, 3), BGR in 0-255
    # kps: np.array, shape (N, 3), x, y, score
    # kps_line: list of tuple, [(i1, i2), ...], i1, i2 are the index of the keypoints
    # bbox: np.array, shape (4, 2), 4 corners of the bbox
    # kp_thre: float, threshold of the keypoint score to visualize, usually given by 2D detector
    # kps_name: list of str, name of the keypoints


    # Get colors for visualizing lines. Obtained by converting form plt 0-1 RGBA colors to opencv 0-255 BGR colors.
    cmap = plt.get_cmap('rainbow')
    colors = [cmap(i) for i in np.linspace(0, 1, len(kps_line))]
    colors = [(c[2] * 255, c[1] * 255, c[0] * 255) for c in colors]
    
    if kps.shape[1] == 2:
        kps = np.concatenate([kps, np.ones((len(kps),1))], axis=1)
    

    # Draw bounding box
    if bbox_xyxy is not None:
        b1 = int(bbox_xyxy[0]), int(bbox_xyxy[1])
        b2 = int(bbox_xyxy[2]), int(bbox_xyxy[1])
        b3 = int(bbox_xyxy[2]), int(bbox_xyxy[3])
        b4 = int(bbox_xyxy[0]), int(bbox_xyxy[3])

        cv2.line(img, b1, b2, color=(255, 255, 0), thickness=5, lineType=cv2.LINE_AA)
        cv2.line(img, b2, b3, color=(255, 255, 0), thickness=5, lineType=cv2.LINE_AA)
        cv2.line(img, b3, b4, color=(255, 255, 0), thickness=5, lineType=cv2.LINE_AA)
        cv2.line(img, b4, b1, color=(255, 255, 0), thickness=5, lineType=cv2.LINE_AA)

    # Draw the keypoints
    for l in range(len(kps_line)):
        i1 = kps_line[l][0]
        i2 = kps_line[l][1]
        
        p1 = kps[i1,0].astype(np.int32), kps[i1,1].astype(np.int32)
        p2 = kps[i2,0].astype(np.int32), kps[i2,1].astype(np.int32)
        if kps[i1,2] > kp_thre and kps[i2,2] > kp_thre:
            cv2.line(img, p1, p2, color=colors[l], thickness=8, lineType=cv2.LINE_AA)
        if kps[i1,2] > kp_thre:
            cv2.circle(img, p1, radius=5, color=colors[l], thickness=-1, lineType=cv2.LINE_AA)
            if kps_name is not None:
                cv2.putText(img, kps_name[i1], (p1[0], p1[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            
        if kps[i2,2] > kp_thre:
            cv2.circle(img, p2, radius=5, color=colors[l], thickness=-1, lineType=cv2.LINE_AA)
            if kps_name is not None:
                cv2.putText(img, kps_name[i2], (p2[0], p2[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    return img





# Start 3D pose visualization.

def init_axis(fig, title, lim_min, lim_max, elev=15,azim= 200):#10,260):
    ax = fig.add_subplot(1, 1, 1, projection="3d")
    ax.view_init(elev, azim)

    ax.set_xlim3d([lim_min[0], lim_max[0]])  
    ax.set_ylim3d([lim_min[1], lim_max[1]])
    ax.set_zlim3d([-0.,1.8])

    ax.set_aspect("auto")

    #set x_ticts
    #ax.set_xticks(np.arange(lim_min[0],lim_max[0]+0.01, 0.2))
    #ax.set_yticks(np.arange(lim_min[1],lim_max[1]+0.01, 0.5))
    #ax.set_zticks(np.arange(-0.5,2+0.01, 0.2))
    
    ax.set_xticklabels([])
    ax.set_yticklabels([])
    ax.set_zticklabels([])
    ax.set_xlabel("X", labelpad=-15,fontsize=20)
    ax.set_ylabel("Z", labelpad=-15,fontsize=20)
    ax.set_zlabel("Y", labelpad=-15,fontsize=20)

    #ax.set_axis_off()
    ax.grid(False)
    ax.view_init(elev=elev, azim=azim)
    #ax.set_title(title, loc="center",fontsize=20, wrap=True, pad=-10)
    return ax


def plot_floor(ax, minx, maxx, miny, maxy, minz):
    # Plot a plane XZ
    verts = [
        [minx, miny, minz],
        [minx, maxy, minz],
        [maxx, maxy, minz],
        [maxx, miny, minz],
    ]
    xz_plane = Poly3DCollection([verts], zorder=1)
    xz_plane.set_facecolor((0.5, 0.5, 0.5, 1))
    ax.add_collection3d(xz_plane)

    # Plot a bigger square plane XZ
    radius = max((maxx - minx), (maxy - miny))

    # center +- radius
    minx_all = (maxx + minx) / 2 - radius
    maxx_all = (maxx + minx) / 2 + radius

    miny_all = (maxy + miny) / 2 - radius
    maxy_all = (maxy + miny) / 2 + radius

    verts = [
        [minx_all, miny_all, minz],
        [minx_all, maxy_all, minz],
        [maxx_all, maxy_all, minz],
        [maxx_all, miny_all, minz],
    ]
    xz_plane = Poly3DCollection([verts], zorder=1)
    xz_plane.set_facecolor((0.5, 0.5, 0.5, 0.5))
    ax.add_collection3d(xz_plane)
    return ax



def render_animation(joints, kinematic_tree, path_output, colors, input_zup=True, has_gt=False, title="", fps=30, figsize=(10,10), agg=True, return_buffer=False):
    if agg:
        matplotlib.use("Agg")

    if input_zup:
        joints=joints.copy()
    else:
        joints=joints[:,:,[0,2,1]].copy()
        joints[:,:,2]=-joints[:,:,2]
    
    joints[:,:,0]-=joints[:,0:1,0]
    joints[:,:,1]-=joints[:,0:1,1]

    x, y, z = 0, 1, 2    
    # Create a figure and initialize 3d plot
    fig = plt.figure(figsize=figsize)
    limits_min = np.round(np.min(joints, axis=(0, 1)), 1)
    limits_min[:2]-=0.5
    limits_max = np.round(np.max(joints, axis=(0, 1)), 1)
    limits_max[:2]+=0.5

    ax = init_axis(fig, title[0] if isinstance(title, list) else title, limits_min, limits_max)

    # Create spline line
    trajectory = joints[:, 0, [x, y]]
    avg_segment_length = (np.mean(np.linalg.norm(np.diff(trajectory, axis=0), axis=1)) + 1e-3)
    draw_offset = int(25 / avg_segment_length)
    (spline_line,) = ax.plot(*trajectory.T, zorder=10, color="white")

    # Create a floor
    minx, miny, _ = joints.min(axis=(0, 1))
    maxx, maxy, _ = joints.max(axis=(0, 1))
    plot_floor(ax, minx, maxx, miny, maxy, 0)

    # Put the character on the floor
    height_offset = np.min(joints[:, :, z])  # Min height
    joints = joints.copy()
    joints[:, :, z] -= height_offset

    # Initialization for redrawing
    lines = []
    initialized = False

    if has_gt:
        njoints=joints.shape[1]//2
        gt_joints=joints[:,njoints:].copy()
        joints=joints[:,:njoints].copy()


    def update(frame):
        nonlocal initialized
        skeleton = joints[frame]
        skeleton_gt = gt_joints[frame] if has_gt else None

        nchains=len(kinematic_tree)

        root = skeleton[0]
        #update_camera(ax, root)

        hcolors = colors
        for index, (chain, color) in enumerate(zip(kinematic_tree, hcolors)):
            alpha = 0.9
            if not initialized:
                lines.append(ax.plot(skeleton[chain, x],skeleton[chain, y],skeleton[chain, z],
                                linewidth=6.0,color=color,alpha=alpha,zorder=20,
                                path_effects=[pe.SimpleLineShadow(), pe.Normal()],))
            else:
                lines[index][0].set_xdata(skeleton[chain, x])
                lines[index][0].set_ydata(skeleton[chain, y])
                lines[index][0].set_3d_properties(skeleton[chain, z])
                lines[index][0].set_color(color)
                lines[index][0].set_alpha(alpha)
        
        if has_gt:        
            for index, (chain, color) in enumerate(zip(kinematic_tree, hcolors)):
                alpha = 0.2
                if not initialized:
                    lines.append(ax.plot(skeleton_gt[chain, x],skeleton_gt[chain, y],skeleton_gt[chain, z],
                                    linewidth=6.0,color=color,alpha=alpha,zorder=20,
                                    path_effects=[pe.SimpleLineShadow(), pe.Normal()],))
                else:
                    lines[index+nchains][0].set_xdata(skeleton_gt[chain, x])
                    lines[index+nchains][0].set_ydata(skeleton_gt[chain, y])
                    lines[index+nchains][0].set_3d_properties(skeleton_gt[chain, z])
                    lines[index+nchains][0].set_color(color)
                    lines[index+nchains][0].set_alpha(alpha)




        left = max(frame - draw_offset, 0)
        right = min(frame + draw_offset, trajectory.shape[0])

        spline_line.set_xdata(trajectory[left:right, 0])
        spline_line.set_ydata(trajectory[left:right, 1])
        spline_line.set_3d_properties(np.zeros_like(trajectory[left:right, 0]))


        ax.set_title(title[frame] if isinstance(title, list) else title, loc="center",fontsize=20, wrap=True, y=0.9)
        initialized = True

    fig.tight_layout()
    frames = joints.shape[0]
    anim = FuncAnimation(fig, update, frames=frames, interval=1000 / fps, repeat=False)
    plt.close()
    anim.save(path_output, fps=fps)

    if not return_buffer:
        return

    frames_3d=[]    
    gif=Image.open(path_output)
    gif.seek(0)
    
    for frame in range(gif.n_frames):
        gif.seek(frame)
        bgr_frame = cv2.cvtColor(np.array(gif.convert("RGB")), cv2.COLOR_RGB2BGR)
        frames_3d.append(bgr_frame)
    
    return frames_3d
    





def project_skel_3d2img(skel,cam_intr,cam_extr=None):
    ndims_skel=skel.ndim
    if ndims_skel==3:
        nframes,njoints=skel.shape[:2]
    else:
        njoints=skel.shape[0]
    skel=skel.reshape([-1,3])

    if cam_extr is not None:
        skel_hom = np.concatenate([skel, np.ones([skel.shape[0], 1])], 1)
        skel_camcoords = cam_extr.dot(skel_hom.transpose()).transpose()[:, :3].astype(np.float32)
    else:
        skel_camcoords=skel
    
    hom_2d = cam_intr.dot(skel_camcoords.transpose()).transpose()
    hom_2d[:,2]=np.where(hom_2d[:,2]<1e-8,1,hom_2d[:,2])
    skel2d = (hom_2d / hom_2d[:, 2:])[:, :2]

    if ndims_skel==3:
        skel2d=skel2d.reshape([nframes,njoints,2])
        
    return skel2d