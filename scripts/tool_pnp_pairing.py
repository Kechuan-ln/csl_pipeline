#!/usr/bin/env python3
"""
ChArUco Board Corner Detection Tool

This tool provides a Gradio web interface for detecting and visualizing ChArUco board 
corner points with their IDs from undistorted images.

Features:
- Load undistorted images and ChArUco board configuration
- Detect ChArUco corners and markers
- Visualize detected corners with IDs
- Interactive web interface using Gradio

Prerequisites:
- OpenCV with ArUco support
- ChArUco board configuration YAML files
"""

import os
import sys
sys.path.append('..')
import yaml
import argparse
import cv2
import gradio as gr
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import json
from utils.io_utils import NumpyEncoder

# Add parent directory to path for imports
sys.path.append('..')

def get_args_parser():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='ChArUco Corner Detection Tool', 
        add_help=True, 
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument('--port', type=int, default=7863, help='Port for Gradio interface')
    parser.add_argument('--share', action='store_true', help='Create public sharing link')
    
    parser.add_argument('--boards', type=str, default='../multical/asset/charuco_b1_2.yaml', 
                       help='Path to default ChArUco configuration file')
    parser.add_argument('--path_image',type=str, default=None, help='Path to undistorted image')
    parser.add_argument('--path_points',type=str, default=None, help='Path to output JSON file')

    return parser

class Annotator:
    def __init__(self, args):
        self.board, self.dictionary, self.aruco_params, self.config = self.load_charuco_config(args.boards)
        self.undistorted_image = cv2.imread(args.path_image)
        self.output_path = args.path_points  # Store JSON output path
        
        if self.undistorted_image is None:
            raise ValueError(f"Could not load image from {args.path_image}")

        marker_corners, marker_ids, charuco_corners, charuco_ids = self.detect_charuco_corners(self.undistorted_image, self.board, self.dictionary, self.aruco_params)

        self.charuco_corners = charuco_corners
        self.charuco_ids = charuco_ids
        
        # Store 2D-3D point correspondences
        self.point_correspondences = []  # List of dicts: {'2d': (x, y), '3d': (x, y, z), 'type': 'detected'/'manual', 'id': corner_id}
        
        # Board parameters for 3D coordinate calculation
        self.square_length = self.config['common']['square_length']
        self.board_size = tuple(self.config['common']['size'])  # (width, height) in squares
        
        

    def load_charuco_config(self, config_path):
        """Load ChArUco board configuration from YAML file."""
    
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        common = config['common']
        board_size = tuple(common['size'])  # (width, height) in squares
        square_length = common['square_length']
        marker_length = common['marker_length']
        
        # Get ArUco dictionary
        aruco_dict_name = common['aruco_dict']
        aruco_dict = getattr(cv2.aruco, f'DICT_{aruco_dict_name}')
        dictionary = cv2.aruco.getPredefinedDictionary(aruco_dict)
        
        # Create ChArUco board
        board = cv2.aruco.CharucoBoard(board_size, square_length, marker_length, dictionary)
        
        # Get detection parameters
        aruco_params = cv2.aruco.DetectorParameters()
        if 'aruco_params' in config:
            params_config = config['aruco_params']
            if 'adaptiveThreshWinSizeMax' in params_config:
                aruco_params.adaptiveThreshWinSizeMax = params_config['adaptiveThreshWinSizeMax']
            if 'adaptiveThreshWinSizeStep' in params_config:
                aruco_params.adaptiveThreshWinSizeStep = params_config['adaptiveThreshWinSizeStep']
        
        
        return board, dictionary, aruco_params, config
    
    def calculate_3d_board_coordinates(self, row, col):
        """Calculate 3D board coordinates from row/column indices."""
        # ChArUco board coordinate system: origin at top-left corner
        # X-axis: right, Y-axis: down, Z-axis: out of board (always 0)
        x = col * self.square_length
        y = row * self.square_length
        z = 0.0
        return (x, y, z)
    
    def get_detected_corners_list(self):
        """Get list of detected corner IDs for dropdown selection."""
        if self.charuco_ids is not None:
            return [f"Corner {int(corner_id)}" for corner_id in self.charuco_ids.flatten()]
        return []
    
    def add_point_correspondence(self, row, col, corner_selection=None, manual_x=None, manual_y=None):
        """Add a 2D-3D point correspondence."""
        try:
            # Calculate 3D board coordinates
            board_3d = self.calculate_3d_board_coordinates(row, col)
            
            if corner_selection and corner_selection != "None":
                # Use detected corner
                corner_id = int(corner_selection.split()[-1])  # Extract ID from "Corner X"
                
                # Find the 2D position of this corner
                corner_idx = None
                if self.charuco_ids is not None:
                    for i, cid in enumerate(self.charuco_ids.flatten()):
                        if int(cid) == corner_id:
                            corner_idx = i
                            break
                
                if corner_idx is not None:
                    corner_pos = self.charuco_corners[corner_idx][0]
                    point_2d = (float(corner_pos[0]), float(corner_pos[1]))
                    
                    correspondence = {
                        '2d': point_2d,
                        '3d': board_3d,
                        'type': 'detected',
                        'id': corner_id,
                        'row': row,
                        'col': col
                    }
                    
                    self.point_correspondences.append(correspondence)
                    return f"Added detected corner {corner_id} at board position ({row}, {col})"
                else:
                    return f"Error: Corner {corner_id} not found in detected corners"
            
            elif manual_x is not None and manual_y is not None:
                # Use manual annotation
                point_2d = (float(manual_x), float(manual_y))
                
                correspondence = {
                    '2d': point_2d,
                    '3d': board_3d,
                    'type': 'manual',
                    'id': len(self.point_correspondences),
                    'row': row,
                    'col': col
                }
                
                self.point_correspondences.append(correspondence)
                return f"Added manual point at ({manual_x}, {manual_y}) for board position ({row}, {col})"
            
            else:
                return "Error: Please select a detected corner or provide manual coordinates"
                
        except Exception as e:
            return f"Error adding correspondence: {str(e)}"
    
    def remove_last_correspondence(self):
        """Remove the last added correspondence."""
        if self.point_correspondences:
            removed = self.point_correspondences.pop()
            return f"Removed correspondence: {removed['type']} point at board ({removed['row']}, {removed['col']})"
        return "No correspondences to remove"
    
    def get_correspondences_summary(self):
        """Get a summary of current point correspondences."""
        if not self.point_correspondences:
            return "No point correspondences added yet."
        
        summary = f"Current correspondences ({len(self.point_correspondences)}):\n"
        for i, corr in enumerate(self.point_correspondences):
            summary += f"{i+1}. {corr['type'].capitalize()} - Board({corr['row']}, {corr['col']}) -> 2D({corr['2d'][0]:.1f}, {corr['2d'][1]:.1f})\n"
        
        return summary
    
    def save_correspondences(self):
        """Save point correspondences to JSON file."""
        if not self.output_path:
            return "Error: No output path specified. Use --path_points argument."
        
        if not self.point_correspondences:
            return "No correspondences to save."
        
        try:
            # Create output directory if it doesn't exist
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
            
            # Save correspondences to JSON
            with open(self.output_path, 'w') as f:
                json.dump(self.point_correspondences, f, separators=(',', ':'), cls=NumpyEncoder)
            
            return f"Saved {len(self.point_correspondences)} correspondences to {self.output_path}"
            
        except Exception as e:
            return f"Error saving correspondences: {str(e)}"
    
    def handle_image_click(self, evt: gr.SelectData):
        """Handle clicks on the image to get 2D coordinates."""
        if evt.index is not None:
            x, y = evt.index[0], evt.index[1]
            return x, y
        return None, None
            
    def detect_charuco_corners(self, image, board, dictionary, aruco_params):
        """Detect ChArUco corners and markers in the image."""
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        # Detect ArUco markers
        detector = cv2.aruco.ArucoDetector(dictionary, aruco_params)
        marker_corners, marker_ids, _ = detector.detectMarkers(gray)
        
        if marker_ids is not None and len(marker_ids) > 0:
            # Interpolate ChArUco corners
            charuco_retval, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(marker_corners, marker_ids, gray, board)
            
            if charuco_retval > 0:
                return marker_corners, marker_ids, charuco_corners, charuco_ids
            else:
                return marker_corners, marker_ids, None, None
        else:
            return None, None, None, None
                

    def visualize_annotation(self):
        """Visualize detected markers, ChArUco corners, and user annotations."""
        vis_image = self.undistorted_image.copy()
        
        # Draw detected ChArUco corners
        charuco_corners = self.charuco_corners
        charuco_ids = self.charuco_ids
        
        if charuco_corners is not None and charuco_ids is not None:
            # Add corner ID labels for detected corners
            for i, corner_id in enumerate(charuco_ids.flatten()):
                corner_pos = charuco_corners[i][0]
                x, y = int(corner_pos[0]), int(corner_pos[1])
                
                # Check if this corner is used in correspondences
                is_used = any(corr['type'] == 'detected' and corr['id'] == int(corner_id) 
                             for corr in self.point_correspondences)
                
                if is_used:
                    # Draw green circle for used detected corners
                    cv2.circle(vis_image, (x, y), 10, (0, 255, 0), -1)
                    cv2.putText(vis_image, str(corner_id), (x + 12, y - 12), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                else:
                    # Draw blue circle for unused detected corners
                    cv2.circle(vis_image, (x, y), 8, (255, 128, 0), -1)
                    cv2.putText(vis_image, str(corner_id), (x + 10, y - 10), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 128, 0), 2)
        
        # Draw user-added correspondences
        for i, corr in enumerate(self.point_correspondences):
            x, y = int(corr['2d'][0]), int(corr['2d'][1])
            
            if corr['type'] == 'manual':
                # Draw red circle for manual points
                cv2.circle(vis_image, (x, y), 8, (0, 0, 255), -1)
                # Add board coordinate label
                label = f"({corr['row']},{corr['col']})"
                cv2.putText(vis_image, label, (x + 15, y - 15), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            else:
                # Add board coordinate label for detected corners
                label = f"({corr['row']},{corr['col']})"
                cv2.putText(vis_image, label, (x - 50, y + 25), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        # Convert to PIL format for display
        vis_image_rgb = cv2.cvtColor(vis_image, cv2.COLOR_BGR2RGB)
        result_image = Image.fromarray(vis_image_rgb)

        return result_image



    def create_annotation_interface(self):
        """Create the Gradio interface."""
        with gr.Blocks(title="ChArUco Corner Calibration Tool") as interface:
            gr.Markdown("# ChArUco Corner Calibration Tool")
            gr.Markdown("Create 2D-3D point correspondences for camera calibration.")
            with gr.Row():
                output_image = gr.Image(
                    label="Image (Click to select manual points)",
                    interactive=False
                )
            with gr.Row():
                # Input controls
                gr.Markdown("### Add Point Correspondence")
                
                with gr.Row():
                    row_input = gr.Number(label="Board Row", value=0, precision=0)
                    col_input = gr.Number(label="Board Column", value=0, precision=0)
                
                detected_dropdown = gr.Dropdown(
                    choices=["None"] + self.get_detected_corners_list(),
                    label="Select Detected Corner",
                    value="None"
                )
                
                gr.Markdown("**OR** Click on image to select manual point:")
                
                with gr.Row():
                    manual_x = gr.Number(label="Manual X", value=None, precision=1)
                    manual_y = gr.Number(label="Manual Y", value=None, precision=1)
                
                with gr.Row():
                    add_btn = gr.Button("Add Correspondence", variant="primary")
                    remove_btn = gr.Button("Remove Last", variant="secondary")
                    refresh_btn = gr.Button("Refresh View", variant="secondary")
                    save_btn = gr.Button("Save to JSON", variant="secondary")
                
                status_text = gr.Textbox(label="Status", interactive=False)
                
                correspondences_text = gr.Textbox(
                    label="Current Correspondences", 
                    lines=8, 
                    interactive=False
                )
            

                    
            
            # Event handlers
            def update_manual_coords(evt: gr.SelectData):
                if evt.index is not None:
                    return evt.index[0], evt.index[1]
                return gr.update(), gr.update()
            
            def reset_selection_inputs():
                """Reset dropdown and manual coordinate inputs when row/col changes."""
                return "None", None, None
            
            # Click on image to get coordinates
            output_image.select(
                fn=update_manual_coords,
                outputs=[manual_x, manual_y]
            )
            
            # Add correspondence
            add_btn.click(
                fn=self.add_point_correspondence,
                inputs=[row_input, col_input, detected_dropdown, manual_x, manual_y],
                outputs=[status_text]
            ).then(
                fn=self.visualize_annotation,
                outputs=[output_image]
            ).then(
                fn=self.get_correspondences_summary,
                outputs=[correspondences_text]
            )
            
            # Remove last correspondence
            remove_btn.click(
                fn=self.remove_last_correspondence,
                outputs=[status_text]
            ).then(
                fn=self.visualize_annotation,
                outputs=[output_image]
            ).then(
                fn=self.get_correspondences_summary,
                outputs=[correspondences_text]
            )
            
            # Refresh visualization
            refresh_btn.click(
                fn=self.visualize_annotation,
                outputs=[output_image]
            ).then(
                fn=self.get_correspondences_summary,
                outputs=[correspondences_text]
            )
            
            # Save correspondences
            save_btn.click(
                fn=self.save_correspondences,
                outputs=[status_text]
            )
            
            # Reset inputs when row or column changes
            row_input.change(
                fn=reset_selection_inputs,
                outputs=[detected_dropdown, manual_x, manual_y]
            )
            
            col_input.change(
                fn=reset_selection_inputs,
                outputs=[detected_dropdown, manual_x, manual_y]
            )
            
            # Auto-load on interface start
            interface.load(
                fn=self.visualize_annotation,
                outputs=[output_image]
            ).then(
                fn=self.get_correspondences_summary,
                outputs=[correspondences_text]
            )
        
        return interface

def main():
    """Main function."""
    annotator=None
    try:
        parser = get_args_parser()
        args = parser.parse_args()

        annotator = Annotator(args)
        
        # Create and launch interface
        interface = annotator.create_annotation_interface()
        interface.launch(
            server_name="0.0.0.0",  # Allow external access
            server_port=args.port,  # Use port from arguments
            share=args.share,       # Use share flag from arguments
            debug=True
        )
    except KeyboardInterrupt:
        print("\n⚠️  Received interrupt signal, saving annotations...")
        if annotator:
            save_result = annotator.save_correspondences()
            print(f"Auto-save result: {save_result}")
    except Exception as e:
        print(f"Error launching bounding box annotation tool: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Auto-save on exit
        if annotator:
            print("💾 Auto-saving correspondences before exit...")
            save_result = annotator.save_correspondences()
            print(f"Auto-save result: {save_result}")

        

if __name__ == "__main__":
    main()