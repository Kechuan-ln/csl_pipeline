# Directory Organisation

One should put all videos under the folder defined by `<image_path>`, so the directory tree becomes

```
├── <image_path>/
|   ├── <cam01>/
|   |   └── <video1>.MP4
|   ├── <cam02>/
|   |   └── <video2>.MP4
└── .../
```

# Intrinsic Calibration

Properly set `--boards` and `--image_path`. 
- Note that `--image_path` is relative to `PATH_ASSETS_VIDEOS`

An example command is

``` bash
python intrinsic.py --boards ./asset/charuco_b3.yaml --image_path intr_0912 --limit_images 1000 --limit_intrinsic 1000 --vis
```


It will calibrate each camera by leveraging images in the corresponding folders. The computation progress is two stages, with both wrapping corresponding opencv functions
- The marker detection refers to `multical/board/charco.py`, function `detect(self, image)`
- The intrinsic calibration refers to `multical/transform/camera.py`, function `calibrate(boards, detections,image_size,...)` 


Notes:
1. If under each `<cam_id>` there are no image files, the program will decompose the MP4 into images. 
    - This is achieved as I hacked `find_cameras()` defined in `multical/image/find.py`
2. Set `min_points` in the board configuration yaml (i.e., followed by ``--boards``), this will discard images that do not have enough courner detections. 
    - This is achieved as I hacked `detect(self,image)` defined in `multical/board/charuco.py`
3. At the end of `intrinsic.py`, one could visualise the board detection.


# Extrinsic Calibration

Properly set `--boards`, `--image_path`, `--calibration`. 
- Note that `--image_path` and `--calibration` are relative to `PATH_ASSETS_VIDEOS`

An exmaple command is

``` bash
python calibrate.py --boards ./asset/charuco.yaml --image_path extr_91122 --camera_pattern '{camera}' --calibration extr_91122/intrinsic.json --fix_intrinsic --limit_images 1000 --vis
```

The computation progress is three stages: board2camera -> camera2basecamera -> bundle adjustment. One could refer to the implementation details for more info.
- In `initialise_poses()` defined in `multical/workspace.py`, it will first calibrate board2camera, where the core functions are `cv2.undistortPoints()` and `cv2.solvePnP()`; it then get relative poses among cameras and relative poses among boards, as achieved by `tables.initialise_poses()`.
- Bundle adjustment has key functions defined in `multical/optimization/calibration.py`, which applies non linear least squares optimization with scipy least_squares based on finite differences of the parameters, on point reprojection error.
    - Parameters: {cameras=False, boards=False, camera_poses=True, board_poses=True, motion=True}, options: {'loss': 'linear', 'tolerance': 0.0001}

Notes:
1. Note that one usually use different sets of videos/images for intrinsic and extrinsic calibrations.
2. The videos MUST be synchronised, as `find_camera_images()` will pair images by referring to filenames. Moreover, the program can handle missing board in some of the frames, as shown in implementation details.
3. If under each `<cam_id>` there are no image files, the program will decompose the MP4 into images. 
4. Set `min_points` in the board configuration yaml (i.e., followed by ``--boards``), this will discard images that do not have enough courner detections. 
5. At the end of `calibrate.py`, one could visualise the board detection and axes projection. For projected 3D axes, 
    - OX, OY, OZ should be in red, green, and blue. 
    - OX should point from id=0 to id=1, with OZ should point inside the board. 
    - The 2D length of OX and OY should be `n_squares(=3)*square_length`


<details> <summary> Implementation Details </summary>

### 1. Image Pairing

The program can handle missing board in some of the frames, as achieved by:
1. __Flexible Detection System__: The system is designed to handle cases where the calibration board is not visible in all cameras simultaneously. Key functions that enable this:
    - `board.has_min_detections()`: Checks if a board has sufficient corner detections for pose estimation
    - `board.estimate_pose_points()`: Only attempts pose estimation if minimum detections are met
    - If a board doesn't have sufficient detections in a frame, it's simply skipped for that camera
2. __Sparse Pose Tables__: The system creates sparse pose tables where:
    - Valid poses are marked with `valid=True`
    - Missing/insufficient detections are marked with `valid=False`
    - The calibration algorithm works with this sparse data structure
3. __Graph-Based Pose Estimation__: The `estimate_relative_poses()` function uses:
    - __Overlap analysis__: Calculates overlaps between camera pairs based on valid detections
    - __Graph connectivity__: Uses `graph.select_pairs()` to find optimal connections between cameras
    - __Robust alignment__: Can estimate relative poses even with partial overlaps



### 2. Code Analysis of Initialisation for Relative Poses

`initialise_poses()` defined in `multical/workspace.py`

#### 2-1. Key Data Structures

##### `self.point_table`
- **Purpose**: A 3D table containing detected corner points from calibration patterns
- **Structure**: Organized as `[camera][frame][board]` - each entry contains detected 2D corner points and validity masks
- **Usage**: Stores all 2D corner detections from calibration boards across all cameras and frames

##### `self.pose_table`
- **Purpose**: A 3D table containing estimated poses of calibration boards relative to each camera
- **Structure**: Organized as `[camera][frame][board]` - each entry contains 4x4 transformation matrices
- **Usage**: Contains initial estimates of where each calibration board was positioned relative to each camera in each frame

##### `self.boards`
- **Purpose**: List of calibration board objects (e.g., checkerboards, ChArUco boards)
- **Contains**: 3D coordinates of board corner points, board geometry, detection methods
- **Usage**: Defines the known 3D structure of calibration patterns used for pose estimation

##### `self.cameras`
- **Purpose**: List of calibrated Camera objects with intrinsic parameters
- **Contains**: Focal length, principal point, distortion coefficients for each camera
- **Usage**: Provides intrinsic camera parameters needed for pose estimation


#### 2-2. Board-to-Camera Transformation Estimation

The core process `estimate_pose_points()` is defined in `multical/multical/board/common.py`, which is invoked by `tables.make_pose_table()->extract_pose()->board.estimate_pose_points()`


```python
def estimate_pose_points(board, camera, detections):
    undistorted = camera.undistort_points(detections.corners)      
    valid, rvec, tvec = cv2.solvePnP(board.points[detections.ids], 
      undistorted, camera.intrinsic, np.zeros(0))
    return rtvec.join(rvec.flatten(), tvec.flatten())
```

#### 2-3. Initial Relative Poses

As achieved by `pose_init`, which is returned by `tables.initialise_poses()` and contains the initial pose estimates for the multi-camera calibration system:


##### `pose_init.camera` (Relative Camera Poses):
```python
camera = estimate_relative_poses(pose_table, axis=0)
```
- **Purpose**: Estimates spatial relationships between cameras in the multi-camera rig
- **Method**: Uses overlapping board detections between cameras to compute relative transformations
- **Process**: Finds camera pairs with sufficient overlapping board observations, uses robust pose alignment, creates spanning tree to connect all cameras

##### `pose_init.board` (Relative Board Poses):
```python
board = estimate_relative_poses_inv(pose_table, axis=2)
```
- **Purpose**: Estimates relative positions of different calibration boards in the scene
- **Method**: Similar to camera poses but operates on the board dimension

##### `pose_init.times` (Rig/Temporal Poses):
```python
# Mathematical relationship: cam @ rig @ board = pose
# Solve for rig: rig = cam^-1 @ pose @ board^-1
board_relative = multiply_tables(pose_table, expand(inverse(board), [0, 1]))
expanded = broadcast_to(expand(camera, [1, 2]), board_relative)
times = relative_between_n(expanded, board_relative, axis=1, inv=True)
```
- **Purpose**: Estimates how the camera rig moved through space over time
- **Mathematical derivation**: Given `cam @ rig @ board = pose`, solves for `rig = cam^-1 @ pose @ board^-1`



### 3. Parameters Explaination in Bundle Adjustment

#### In iteration table

**Iteration**
- Current optimization step number
- Shows how many iterations have been completed

**Total nfev**
- Total number of function evaluations (objective function calls)
- Each evaluation computes reprojection errors for all cameras and points
- Higher numbers indicate more computational work


**Cost**
- Current value of the objective function (sum of squared reprojection errors)
- Measured in squared pixels
- Should decrease with each iteration for successful optimization

**Cost reduction**
- How much the cost decreased in this iteration
- Positive values indicate improvement
- When this becomes very small, optimization is converging

**Step norm**
- Magnitude of parameter changes in this iteration
- Large values: significant parameter updates
- Small values: fine-tuning, approaching convergence

**Optimality**
- Measure of how close to optimal the current solution is
- Related to gradient norm (steepness of cost function)
- Should approach zero at convergence
- Small values indicate the solution is near optimal


#### Final output
```python
if self.inlier_mask is not None:
    info(f"{stage} reprojection RMS={inliers.rms:.3f} ({overall.rms:.3f}), "
        f"n={inliers.n} ({overall.n}), quantiles={inliers.quantiles} ({overall.quantiles})")
else:
    info(f"{stage} reprojection RMS={overall.rms:.3f}, n={overall.n}, "
        f"quantiles={overall.quantiles}")
```

where quantiles is explained as
- __quantiles[0]__ = __Minimum error__ (0% quantile) - smallest reprojection error
- __quantiles[1]__ = __First quartile (Q1)__ (25% quantile) - 25% of errors are below this
- __quantiles[2]__ = __Median (Q2)__ (50% quantile) - middle value of all errors
- __quantiles[3]__ = __Third quartile (Q3)__ (75% quantile) - 75% of errors are below this
- __quantiles[4]__ = __Maximum error__ (100% quantile) - largest reprojection error



 </details>



 # Examine Extrinsic Calibration

 This is to validate the estimated intrinsid and extrinsic (`--reference_json`), by referring another validation recording (`--image_path`) and comparing the reprojection error, as well as do visualisation.

 **Step 1** Compute extrinsic for validation recording, as we still need the board2basecam. The output json is under `--image_path`.

 **Step 2** Refer to `check_calibration.py`
 - Properly set `--image_path` and `--reference_json`, which are under `PATH_ASSETS_VIDEOS`
 - Properly set `--min_det`, indicating the threshold of enough corner detection, so that a frame will being considered.
 - Set `--vis` to output framewise visualisation.
 - It will automaticly refer to `<image_path>/calibration.json` for board2basecam. However, intrinsics and extrinsics are from `--reference_json`.

 For example,
 ```bash
 python check_calibration.py --image_path extr_11052 --reference_json extr_11051/calibration.json --boards ./asset/charuco_b1_2.yaml --min_det 20 --vis
 ```

 It will output RMS between board projection and detection, as well as framewise visualisation.
