import os
import subprocess
import json
import glob
import tempfile
import numpy as np
import cv2


def convert_video_to_images(path_video, dir_images, img_format=None, fps=None, duration=None, ss=None, image_format='png'):
    """
    Convert video to image sequence.

    Args:
        path_video: Path to input video file
        dir_images: Directory to save extracted images
        img_format: (Optional) Complete format pattern like 'frame_%04d.png'.
                   If not provided, uses image_format parameter instead.
        fps: Frame rate for extraction (optional)
        duration: Duration in seconds to extract (optional)
        ss: Start offset in seconds (optional)
        image_format: Output image format ('png' or 'jpg'), default 'png'.
                     Only used if img_format is None.
    """
    if not os.path.exists(dir_images):
        os.makedirs(dir_images)

    # Handle img_format: if provided, use it directly; otherwise construct from image_format
    if img_format is None:
        img_format = f"frame_%04d.{image_format}"

    command = ["ffmpeg",  "-i", path_video]
    if ss is not None:
        command += ["-ss", str(ss)]

    if duration is not None:
        command += ["-t", str(duration)]

    if fps is not None:
        command += ["-vf", f"fps={fps}"]
    else:
        command +=['-vsync', '0', '-q:v', '1', ]

    command += [f"{dir_images}/{img_format}"]
    print("COMMAND:", ' '.join(command))

    subprocess.run(command)


def convert_images_to_video(path_video, dir_images, img_format, fps, use_yuv420p=False, rm_dir_images=False):
    image_pattern = os.path.join(dir_images, img_format)

    if use_yuv420p:
        first_pass_cmd = [
            "ffmpeg",
            "-framerate", str(fps),
            "-i", image_pattern,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-pix_fmt", "yuv420p",
            "-y", path_video,
        ]
    else:
        first_pass_cmd = [
            "ffmpeg",
            "-framerate", str(fps),
            "-i", image_pattern,
            "-c:v", "libx264",
            "-y", path_video,
        ]
    subprocess.run(first_pass_cmd)

    if rm_dir_images:
        subprocess.run(["rm", "-rf", dir_images])


def convert_mp4_to_looping_gif(path_mp4):
    """
    Convert an mp4 video to a looping gif with the same name in the same folder.

    Args:
        path_mp4: Path to the input mp4 file

    Returns:
        path_gif: Path to the output gif file
    """
    # Get the directory and filename without extension
    dir_name = os.path.dirname(path_mp4)
    base_name = os.path.splitext(os.path.basename(path_mp4))[0]

    # Create output path with .gif extension
    path_gif = os.path.join(dir_name, f"{base_name}.gif")

    # FFmpeg command to convert mp4 to looping gif
    # loop=0 means infinite loop
    # Uses original fps and scale from the mp4
    command = [
        "ffmpeg",
        "-i", path_mp4,
        "-loop", "0",
        "-y",  # Overwrite output file if it exists
        path_gif
    ]

    print("COMMAND:", ' '.join(command))
    subprocess.run(command)

    print(f"Converted {path_mp4} to looping gif: {path_gif}")
    return path_gif




def stack_images_grid(image_paths, output_path, rows, cols):
    """
    Stack a list of images into a grid layout and save to output path.
    Uses numpy reshape and transpose for efficient grid creation.

    Args:
        image_paths: List of paths to input images
        output_path: Path where the stacked image will be saved
        rows: Number of rows in the grid
        cols: Number of columns in the grid
    """

    num_slots = rows * cols
    if len(image_paths) > num_slots:
        print(f"Warning: {len(image_paths)} images provided but grid only has {num_slots} slots. Extra images will be ignored.")
        image_paths = image_paths[:num_slots]

    # Read all images
    images = []
    for path in image_paths:
        img = cv2.imread(path)
        images.append(img)


    assert len(images)==num_slots, f"Number of images ({len(images)}) does not match grid size ({num_slots})"

    h, w = images[0].shape[:2]

    # Stack into numpy array: (N, H, W, C)
    image_batch = np.array(images)

    # Reshape and transpose to create grid
    # (N, H, W, C) -> (rows, cols, H, W, C) -> (rows, H, cols, W, C) -> (rows*H, cols*W, C)
    grid = (image_batch.reshape(rows, cols, h, w, -1)
            .transpose(0, 2, 1, 3, 4)
            .reshape(rows * h, cols * w, -1))

    # Write output
    cv2.imwrite(output_path, grid)


def stack_videos_grid(video_paths, output_path, rows, cols, scale_width, scale_height):
    """
    Stack a list of videos into a grid layout with custom rows, columns, and scaling.

    Args:
        video_paths: List of paths to input videos
        output_path: Path where the stacked video will be saved
        rows: Number of rows in the grid
        cols: Number of columns in the grid
        scale_width: Width to scale each video to
        scale_height: Height to scale each video to
    """
    num_slots = rows * cols
    if len(video_paths) > num_slots:
        print(f"Warning: {len(video_paths)} videos provided but grid only has {num_slots} slots. Extra videos will be ignored.")
        video_paths = video_paths[:num_slots]

    assert len(video_paths) == num_slots, f"Number of videos ({len(video_paths)}) does not match grid size ({num_slots})"

    # check the durations of all videos
    durations = []
    for path in video_paths:
        cmd = ["ffprobe", "-v", "error", "-show_entries",
               "format=duration", "-of",
               "default=noprint_wrappers=1:nokey=1", path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        duration = float(result.stdout.strip())
        durations.append(duration)
        
    durations.sort()
    print("Video durations (s):", durations)
    min_duration = min(durations)
    max_duration = max(durations)
    print(f"  Min duration: {min_duration:.2f}s")
    print(f"  Max duration: {max_duration:.2f}s")
    assert max_duration - min_duration < 0.1, "Videos have significantly different durations."

    # FFmpeg command initialization
    cmd = ["ffmpeg"]

    # Add all video inputs to the command
    for path in video_paths:
        cmd.extend(["-i", path])

    # Build filter_complex string
    # First, scale all videos
    filter_parts = []
    for i in range(len(video_paths)):
        filter_parts.append(f"[{i}:v]scale={scale_width}:{scale_height}[v{i}]")

    # Handle different grid configurations
    if rows == 1 and cols == 1:
        # Single video, just use the scaled version
        filter_parts.append(f"[v0]copy[v]")
    elif rows == 1:
        # Single row, only hstack
        inputs = ''.join([f"[v{i}]" for i in range(cols)])
        filter_parts.append(f"{inputs}hstack=inputs={cols}[v]")
    elif cols == 1:
        # Single column, only vstack
        inputs = ''.join([f"[v{i}]" for i in range(rows)])
        filter_parts.append(f"{inputs}vstack=inputs={rows}[v]")
    else:
        # Multiple rows and columns, need both hstack and vstack
        # Create rows by hstacking
        for row_idx in range(rows):
            start_idx = row_idx * cols
            end_idx = start_idx + cols
            inputs = ''.join([f"[v{i}]" for i in range(start_idx, end_idx)])
            filter_parts.append(f"{inputs}hstack=inputs={cols}[row{row_idx}]")

        # Stack all rows vertically
        row_inputs = ''.join([f"[row{i}]" for i in range(rows)])
        filter_parts.append(f"{row_inputs}vstack=inputs={rows}[v]")

    filter_str = ';'.join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_str,
        "-map", "[v]",
        "-c:v", "libx264",
        "-y",
        output_path
    ])

    print("COMMAND:", ' '.join(cmd))
    subprocess.run(cmd)


def load_frames_from_video(video_path, start_frame_idx=0, end_frame_idx=-1, step=1):
    cap = cv2.VideoCapture(video_path)
    print("Loading video from", video_path)
    if not cap.isOpened():
        print("Error: Could not open video.")
        exit(0)

    list_frames=[]
    cnt=0
    while True:
        ret, frame = cap.read()
        cnt+=1
        if not ret or (end_frame_idx!=-1 and cnt>=end_frame_idx):
            break
        if cnt<start_frame_idx or (cnt-start_frame_idx)%step!=0:
            continue
            
        list_frames.append(frame)
        
    cap.release()
    return list_frames


def save_into_video(video_path, list_images, fps):
    height, width, _ = list_images[0].shape

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # Codec for mp4
    video_writer = cv2.VideoWriter(video_path, fourcc, fps, (width, height))

    for image in list_images:
        video_writer.write(image)

    video_writer.release()


def extract_frames(root_dir, out_dir, input_tags, output_tags, start_idx, end_idx):
    for in_tag, out_tag in zip(input_tags, output_tags):
        print(in_tag, out_tag)
        os.makedirs(os.path.join(out_dir, out_tag), exist_ok=True)
        for frame_idx in range(start_idx, end_idx):
            path_cframe=os.path.join(root_dir, in_tag, "frame_{:04d}.png".format(frame_idx))
            path_oframe=os.path.join(out_dir, out_tag, "frame_{:04d}.png".format(frame_idx))
            print(path_cframe, path_oframe)
            subprocess.run(["cp", path_cframe, path_oframe])




class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)



def load_manual_2d_bbox_json(dir_detection_json, seq_name):
    # load 2D bounding box detections
    dict_det2ds = {}
    json_files = glob.glob(os.path.join(dir_detection_json, f"{seq_name}_*.json"))
    json_files.sort()  # Sort files to ensure consistent order
    print("Loading manual 2D bbox from:", json_files)
    set_frame_ids = set()
    for cpath_json in json_files:
        # Extract camera info from filename (assuming format like "seq_name_cam00.json")
        cam_key = cpath_json.split('/')[-1].replace('.json', '').split('_')[-1]

        with open(cpath_json, 'r') as f:
            json_data = json.load(f)
                                       
            dict_det2ds[cam_key] = json_data
            set_frame_ids.update(json_data.keys())

    set_frame_ids = sorted(set_frame_ids, key=lambda x: int(x))
    
    return dict_det2ds, set_frame_ids


def load_yolo_track_json(path_json_seq):
    with open(path_json_seq, 'r') as f:
        json_data = json.load(f)
    
    return_data = {}
    for frame_key in json_data:
        return_data[frame_key] = {}
        return_data[frame_key]['auto_detect'] = json_data[frame_key]
    
    return return_data
            

def load_vitpose_json(prefix_json_seq):
    if os.path.exists(prefix_json_seq+'.json'):
        json_files=[prefix_json_seq+'.json']
    else:
        json_files = glob.glob(prefix_json_seq+'_*.json')
        json_files.sort()  # Sort files to ensure consistent order
    
    print("Loading vitpose json from:", json_files)
    all_json_data = {}
    for path_json in json_files:
        with open(path_json, 'r') as f:
            json_data = json.load(f)
        
        for frame_key in json_data:
            frame_data = json_data[frame_key]
            for kk in ['vitpose_2d', 'annotation_2d', 'reproj_err','triangulated_3d', 'refined_3d']:
                if kk not in frame_data:
                    continue
                if isinstance(frame_data[kk], dict):
                    for cam_key, v in frame_data[kk].items():
                        if isinstance(v, list):
                            frame_data[kk][cam_key] = np.array(v)
                elif isinstance(frame_data[kk], list):
                    frame_data[kk] = np.array(frame_data[kk])
            
            
            # Merge data to all_json_data
            if frame_key not in all_json_data:
                all_json_data[frame_key] = frame_data
            else:
                for k, v in frame_data.items():
                    # extend the dictionary
                    all_json_data[frame_key][k].update(v)
    return all_json_data


def load_vitpose_pass_fail_json(prefix_json_seq):
    json_files = glob.glob(prefix_json_seq+'_pf*.json')
    # sort by index after '_pf'
    json_files.sort(key=lambda x: int(os.path.basename(x).split('_pf')[-1].split('.json')[0]))

    all_json_data = {}
    for path_json in json_files:
        print(path_json)
        with open(path_json, 'r') as f:
            json_data = json.load(f)
        all_json_data.update(json_data)

    return all_json_data

def load_manual_keypoint_json(prefix_json_seq):
    paths_json_seq = [prefix_json_seq+'.json']
    print("Loading manual keypoint json from:", paths_json_seq)

    json_data = {}
    for cpath_json in paths_json_seq:
        with open(cpath_json, 'r') as f:
            cjson_data = json.load(f)
            for frame_key in cjson_data:
                frame_data = cjson_data[frame_key]
                for kk in ['manual_2d','manual_flag','need_annot_flag']:
                    if kk not in frame_data:
                        continue
                    if isinstance(frame_data[kk], dict):
                        for cam_key, v in frame_data[kk].items():
                            if isinstance(v, list):
                                frame_data[kk][cam_key] = np.array(v)
                    elif isinstance(frame_data[kk], list):
                        frame_data[kk] = np.array(frame_data[kk])
                    
                json_data[frame_key] = frame_data

    return json_data


def load_3d_keypoint_json(prefix_json_seq):
    return load_vitpose_json(prefix_json_seq)
