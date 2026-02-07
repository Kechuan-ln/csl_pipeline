import json
import os
from intrinsics_to_fov import extract_camera_parameters, compute_fov_from_intrinsics


def combine_intrinsics_with_fov(dir_folder, list_cams, output_path):
    """
    Combine intrinsics.json files from multiple cameras and add field of view from fov.txt
    
    Args:
        dir_folder: Base directory containing camera folders
        list_cams: List of camera folder names
        output_path: Path to save combined intrinsics file
    """
    combined_json = {"cameras": {}}
    
    for cam_tag in list_cams:
        cam_path = os.path.join(dir_folder, cam_tag)
        path_intr = os.path.join(cam_path, "intrinsic.json")
        path_log = os.path.join(cam_path, "log.txt")
        
        # Load intrinsics for this camera
        assert os.path.exists(path_intr), f"Intrinsic file not found for {cam_tag}: {path_intr}"
        with open(path_intr, 'r') as f:
            intrinsics_data = json.load(f)
        
        # Extract camera data - consider only "cameras" field
        assert len(intrinsics_data.get("cameras", {}))==1, f"Expected exactly one camera in {path_intr}"
        for cam_key, cam_data in intrinsics_data["cameras"].items():
            # Use cam_tag as the key for the combined json
            combined_cam_key = cam_tag
            combined_json["cameras"][combined_cam_key] = cam_data.copy()

            fx, fy, cx, cy, width, height = extract_camera_parameters(cam_data)
            fov_h, fov_v, fov_d = compute_fov_from_intrinsics(fx, fy, width, height)
            
            # Add FOV data
            fov_data = {"horizontal": fov_h, "vertical": fov_v,  "diagonal": fov_d}
            combined_json["cameras"][combined_cam_key]["fov"] = fov_data
            
            
            assert os.path.exists(path_log), f"Log file not found for {cam_tag}: {path_log}"
            with open(path_log, 'r') as f:
                log_content = f.read().strip()
                
                lines = log_content.split('\n')
                for line in lines[::-1]:  # Reverse order to find last occurrence
                    if 'RMS=' not in line:
                        continue

                    rms_value = float(line.split('RMS=')[1].strip())
                    combined_json["cameras"][combined_cam_key]["rms"] = rms_value
                    print(f"{cam_tag}, FOV: H={fov_data.get('horizontal', 'N/A'):.2f}°, V={fov_data.get('vertical', 'N/A'):.2f}°, D={fov_data.get('diagonal', 'N/A'):.2f}° RMS: {rms_value:.2f}")
                    break
                    
                    
    
    # Save combined intrinsics
    with open(output_path, 'w') as f:
        json.dump(combined_json, f, indent=2)
    
    print(f"Combined intrinsics saved to: {output_path}")
    print(f"Total cameras: {len(combined_json['cameras'])}")


if __name__ == "__main__":
    dir_folder = '../assets/videos/intr_hyperoff_accept/'
    list_cams = ['cam2','cam3','cam4','cam5','cam6','cam7','cam8','cam9','cam1','cam10','cam11','cam12','cam15','cam16','cam17','cam18']
    output_path = os.path.join(dir_folder, 'combined_intrinsic.json')
    
    combine_intrinsics_with_fov(dir_folder, list_cams, output_path)